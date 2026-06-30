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

        text = str(event.get("text") or "").strip()
        if text:
            await self._telegram.send_message(text, event_id)
            logger.info("event_id=%s route=telegram_message", event_id)

        files = event.get("files") or []
        if isinstance(files, list):
            for file_info in files:
                if isinstance(file_info, dict):
                    await self._process_file(event_id, file_info)

    async def _process_file(self, event_id: str, file_info: dict[str, Any]) -> None:
        file_id = str(file_info.get("id") or "unknown")
        filename = _safe_filename(str(file_info.get("name") or file_info.get("title") or file_id))
        mime_type = str(file_info.get("mimetype") or "application/octet-stream")
        filetype = str(file_info.get("filetype") or "").lower()
        declared_size = int(file_info.get("size") or 0)
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
