from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import Settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramResult:
    ok: bool
    size_error: bool = False
    detail: str = ""


class TelegramClient:
    def __init__(self, settings: Settings) -> None:
        self._token = settings.telegram_bot_token
        self._chat_id = settings.telegram_chat_id
        self._timeout = settings.request_timeout_seconds
        self._base_url = f"https://api.telegram.org/bot{self._token}"

    async def send_message(self, text: str, event_id: str) -> TelegramResult:
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "disable_web_page_preview": False,
        }
        return await self._post("sendMessage", event_id, data=payload)

    async def send_document(self, path: Path, filename: str, mime_type: str, event_id: str) -> TelegramResult:
        with path.open("rb") as handle:
            files = {"document": (filename, handle, mime_type)}
            data = {"chat_id": self._chat_id}
            return await self._post("sendDocument", event_id, data=data, files=files)

    async def _post(
        self,
        method: str,
        event_id: str,
        data: dict[str, str | bool],
        files: dict[str, tuple[str, object, str]] | None = None,
    ) -> TelegramResult:
        url = f"{self._base_url}/{method}"
        last_detail = ""
        for attempt in range(1, 4):
            try:
                if files:
                    for _, handle, _ in files.values():
                        if hasattr(handle, "seek"):
                            handle.seek(0)
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(url, data=data, files=files)

                if response.status_code in (408, 429, 500, 502, 503, 504):
                    last_detail = _response_detail(response)
                    if attempt < 3:
                        logger.warning(
                            "event_id=%s telegram_method=%s status=%s attempt=%s retry=true",
                            event_id,
                            method,
                            response.status_code,
                            attempt,
                        )
                        await asyncio.sleep(2 ** (attempt - 1))
                        continue

                if response.status_code == 413:
                    return TelegramResult(ok=False, size_error=True, detail=_response_detail(response))

                if response.is_success:
                    payload = response.json()
                    if payload.get("ok"):
                        return TelegramResult(ok=True)
                    detail = str(payload.get("description") or "")
                    return TelegramResult(ok=False, size_error=_is_size_error(detail), detail=detail)

                detail = _response_detail(response)
                return TelegramResult(ok=False, size_error=_is_size_error(detail), detail=detail)
            except httpx.HTTPError as exc:
                last_detail = exc.__class__.__name__
                if attempt == 3:
                    return TelegramResult(ok=False, detail=last_detail)
                logger.warning(
                    "event_id=%s telegram_method=%s attempt=%s retry=true error=%s",
                    event_id,
                    method,
                    attempt,
                    exc.__class__.__name__,
                )
                await asyncio.sleep(2 ** (attempt - 1))

        return TelegramResult(ok=False, detail=last_detail)


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300]
    return str(payload.get("description") or payload)[:300]


def _is_size_error(detail: str) -> bool:
    lowered = detail.lower()
    return "file is too big" in lowered or "request entity too large" in lowered or "payload too large" in lowered
