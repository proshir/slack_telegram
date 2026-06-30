from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings
from app.drive import DriveUploader
from app.slack import is_bot_message, is_message_event
from app.telegram import TelegramClient


logger = logging.getLogger(__name__)

VIDEO_FILETYPES = {"mp4", "mov", "m4v", "avi", "mkv", "webm"}


class SlackEventProcessor:
    def __init__(self, settings: Settings, telegram: TelegramClient, drive: DriveUploader) -> None:
        self._settings = settings
        self._telegram = telegram
        self._drive = drive

    async def process(self, event_id: str, event: dict[str, Any]) -> None:
        if not is_message_event(event):
            logger.info("event_id=%s ignored_reason=not_message_event", event_id)
            return
        if is_bot_message(event):
            logger.info("event_id=%s ignored_reason=bot_message", event_id)
            return

        channel_id = str(event.get("channel") or "")
        if channel_id not in self._settings.slack_channel_ids:
            logger.info("event_id=%s channel_id=%s ignored_reason=channel_not_allowed", event_id, channel_id)
            return

        texts = _extract_texts(event)
        for text in texts:
            await self._telegram.send_message(text, event_id)
            logger.info("event_id=%s route=telegram_message", event_id)

        for file_info in _extract_files(event):
            await self._process_file(event_id, file_info)

    async def _process_file(self, event_id: str, file_info: dict[str, Any]) -> None:
        file_id = str(file_info.get("id") or "unknown")
        filename = _safe_filename(str(file_info.get("name") or file_info.get("title") or file_id))
        mime_type = str(file_info.get("mimetype") or "application/octet-stream")
        filetype = str(file_info.get("filetype") or "").lower()
        declared_size = _safe_int(file_info.get("size"))
        url = str(file_info.get("url_private_download") or file_info.get("url_private") or "")

        logger.info(
            "event_id=%s file_id=%s filename=%s mime_type=%s declared_size=%s",
            event_id,
            file_id,
            filename,
            mime_type,
            declared_size,
        )

        if not url:
            logger.warning("event_id=%s file_id=%s skipped_reason=missing_private_download_url", event_id, file_id)
            return

        path: Path | None = None
        try:
            path = await self._download_slack_file(url, filename, event_id, file_id)
            actual_size = path.stat().st_size
            is_video = mime_type.startswith("video/") or filetype in VIDEO_FILETYPES
            is_oversized = max(declared_size, actual_size) > self._settings.telegram_max_upload_bytes

            if is_video:
                await self._send_drive_link(path, filename, mime_type, event_id, file_id, "video")
            elif is_oversized:
                await self._send_drive_link(path, filename, mime_type, event_id, file_id, "telegram_size_limit")
            else:
                result = await self._telegram.send_document(path, filename, mime_type, event_id)
                if result.size_error:
                    logger.info("event_id=%s file_id=%s telegram_size_error=true fallback=drive", event_id, file_id)
                    await self._send_drive_link(path, filename, mime_type, event_id, file_id, "telegram_rejected_size")
                elif not result.ok:
                    logger.error("event_id=%s file_id=%s telegram_upload_failed=%s", event_id, file_id, result.detail)
                else:
                    logger.info("event_id=%s file_id=%s route=telegram_document", event_id, file_id)
        finally:
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("event_id=%s file_id=%s temp_file_cleanup_failed=true", event_id, file_id)

    async def _send_drive_link(
        self,
        path: Path,
        filename: str,
        mime_type: str,
        event_id: str,
        file_id: str,
        reason: str,
    ) -> None:
        link = await self._drive.upload_file(path, filename, mime_type, event_id)
        await self._telegram.send_message(f"{filename}\n{link}", event_id)
        logger.info("event_id=%s file_id=%s route=drive reason=%s", event_id, file_id, reason)

    async def _download_slack_file(self, url: str, filename: str, event_id: str, file_id: str) -> Path:
        suffix = Path(filename).suffix[:32]
        with tempfile.NamedTemporaryFile(prefix="slack_", suffix=suffix, delete=False) as tmp:
            path = Path(tmp.name)

        headers = {"Authorization": f"Bearer {self._settings.slack_bot_token}"}
        timeout = self._settings.request_timeout_seconds
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                    async with client.stream("GET", url, headers=headers) as response:
                        if response.status_code in (408, 429, 500, 502, 503, 504):
                            raise httpx.HTTPStatusError(
                                "transient Slack download failure",
                                request=response.request,
                                response=response,
                            )
                        response.raise_for_status()
                        with path.open("wb") as out_file:
                            async for chunk in response.aiter_bytes():
                                out_file.write(chunk)
                logger.info("event_id=%s file_id=%s slack_downloaded=true", event_id, file_id)
                return path
            except (httpx.HTTPError, OSError) as exc:
                last_error = exc
                if attempt == 3:
                    path.unlink(missing_ok=True)
                    raise
                logger.warning(
                    "event_id=%s file_id=%s slack_download_retry=true attempt=%s",
                    event_id,
                    file_id,
                    attempt,
                )
        path.unlink(missing_ok=True)
        raise RuntimeError("Slack file download failed") from last_error


def _safe_filename(filename: str) -> str:
    cleaned = "".join(char for char in filename if char.isalnum() or char in (" ", ".", "_", "-")).strip()
    return cleaned[:180] or "slack-file"


def _extract_texts(event: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    seen_texts: set[str] = set()
    seen_objects: set[int] = set()

    def add(raw: Any) -> None:
        if not isinstance(raw, str):
            return
        text = raw.strip()
        if not text or text in seen_texts:
            return
        seen_texts.add(text)
        texts.append(text)

    def collect_blocks(raw_blocks: Any) -> None:
        if not isinstance(raw_blocks, list):
            return
        _collect_block_text(raw_blocks, add)

    def collect_message(message: dict[str, Any]) -> None:
        object_id = id(message)
        if object_id in seen_objects:
            return
        seen_objects.add(object_id)

        add(message.get("text"))
        collect_blocks(message.get("blocks"))
        collect_blocks(message.get("message_blocks"))

        attachments = message.get("attachments")
        if isinstance(attachments, list):
            for attachment in attachments:
                if isinstance(attachment, dict):
                    collect_attachment(attachment)

        for key in ("message", "original_message", "root", "source"):
            nested_message = message.get(key)
            if isinstance(nested_message, dict):
                collect_message(nested_message)

    def collect_attachment(attachment: dict[str, Any]) -> None:
        object_id = id(attachment)
        if object_id in seen_objects:
            return
        seen_objects.add(object_id)

        before_count = len(texts)
        add(attachment.get("pretext"))
        add(attachment.get("text"))
        collect_blocks(attachment.get("blocks"))
        collect_blocks(attachment.get("message_blocks"))
        if len(texts) == before_count:
            add(attachment.get("fallback"))

        for key in ("message", "original_message", "root", "source"):
            nested_message = attachment.get(key)
            if isinstance(nested_message, dict):
                collect_message(nested_message)

    collect_message(event)
    return texts


def _collect_block_text(value: Any, add: Any) -> None:
    if isinstance(value, dict):
        text_value = value.get("text")
        if isinstance(text_value, str):
            add(text_value)
        elif isinstance(text_value, dict):
            nested_text = text_value.get("text")
            if isinstance(nested_text, str):
                add(nested_text)

        for nested_value in value.values():
            if isinstance(nested_value, dict | list):
                _collect_block_text(nested_value, add)
    elif isinstance(value, list):
        for item in value:
            _collect_block_text(item, add)


def _extract_files(event: dict[str, Any]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    seen_files: dict[str, int] = {}
    seen_objects: set[int] = set()

    def add(file_info: dict[str, Any]) -> None:
        key = str(file_info.get("id") or file_info.get("url_private_download") or file_info.get("url_private") or "")
        if not key:
            return
        existing_index = seen_files.get(key)
        if existing_index is not None:
            existing_file = files[existing_index]
            if not _has_private_file_url(existing_file) and _has_private_file_url(file_info):
                files[existing_index] = file_info
            return
        seen_files[key] = len(files)
        files.append(file_info)

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            object_id = id(value)
            if object_id in seen_objects:
                return
            seen_objects.add(object_id)

            if _looks_like_slack_file(value):
                add(value)
                return

            for nested_value in value.values():
                if isinstance(nested_value, dict | list):
                    walk(nested_value)
        elif isinstance(value, list):
            object_id = id(value)
            if object_id in seen_objects:
                return
            seen_objects.add(object_id)
            for item in value:
                walk(item)

    walk(event)
    return files


def _looks_like_slack_file(value: dict[str, Any]) -> bool:
    if not value.get("id"):
        return False
    if _has_private_file_url(value):
        return True
    return any(key in value for key in ("mimetype", "filetype", "size")) and any(
        key in value for key in ("name", "title", "mode")
    )


def _has_private_file_url(value: dict[str, Any]) -> bool:
    return bool(value.get("url_private_download") or value.get("url_private"))


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
