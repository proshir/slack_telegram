from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from app.config import Settings


logger = logging.getLogger(__name__)

DRIVE_SCOPES = ("https://www.googleapis.com/auth/drive.file",)


class DriveUploader:
    def __init__(self, settings: Settings) -> None:
        self._oauth_token_path = settings.google_oauth_token
        self._folder_id = settings.google_drive_folder_id

    async def upload_file(self, path: Path, filename: str, mime_type: str | None, event_id: str) -> str:
        return await asyncio.to_thread(self._upload_file_sync, path, filename, mime_type, event_id)

    def _upload_file_sync(self, path: Path, filename: str, mime_type: str | None, event_id: str) -> str:
        credentials = self._load_credentials(event_id)
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        media = MediaFileUpload(str(path), mimetype=mime_type or "application/octet-stream", resumable=True)
        body = {"name": filename, "parents": [self._folder_id]}

        response = self._execute_with_retry(
            service.files().create(
                body=body,
                media_body=media,
                fields="id,webViewLink",
                supportsAllDrives=True,
            ),
            "drive_upload",
            event_id,
        )
        file_id = response["id"]

        link = response.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
        logger.info("event_id=%s drive_file_id=%s route=drive_link access=restricted", event_id, file_id)
        return link

    def _load_credentials(self, event_id: str) -> Credentials:
        token_path = Path(self._oauth_token_path)
        if not token_path.exists():
            raise RuntimeError(
                f"Google OAuth token file not found at {token_path}. "
                "Run python -m app.google_oauth_auth first."
            )

        credentials = Credentials.from_authorized_user_file(str(token_path), scopes=DRIVE_SCOPES)
        if credentials.valid:
            return credentials
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self._save_refreshed_oauth_token(token_path, credentials, event_id)
            return credentials
        raise RuntimeError(
            f"Google OAuth token at {token_path} is invalid or missing a refresh token. "
            "Run python -m app.google_oauth_auth again."
        )

    def _save_refreshed_oauth_token(self, token_path: Path, credentials: Credentials, event_id: str) -> None:
        try:
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(credentials.to_json(), encoding="utf-8")
        except OSError:
            logger.warning("event_id=%s google_oauth_token_refresh_save_failed=true", event_id)
        else:
            logger.info("event_id=%s google_oauth_token_refreshed=true", event_id)

    def _execute_with_retry(self, request: Any, operation: str, event_id: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                return request.execute()
            except HttpError as exc:
                last_error = exc
                status = getattr(exc.resp, "status", None)
                if status not in (408, 429, 500, 502, 503, 504) or attempt == 3:
                    raise
                logger.warning(
                    "event_id=%s operation=%s status=%s attempt=%s retry=true",
                    event_id,
                    operation,
                    status,
                    attempt,
                )
                time.sleep(2 ** (attempt - 1))
        raise RuntimeError(f"{operation} failed") from last_error
