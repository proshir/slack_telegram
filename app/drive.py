from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from app.config import Settings


logger = logging.getLogger(__name__)

DRIVE_SCOPES = ("https://www.googleapis.com/auth/drive.file",)


class DriveUploader:
    def __init__(self, settings: Settings) -> None:
        self._credentials_path = settings.google_application_credentials
        self._folder_id = settings.google_drive_folder_id

    async def upload_file(self, path: Path, filename: str, mime_type: str | None, event_id: str) -> str:
        return await asyncio.to_thread(self._upload_file_sync, path, filename, mime_type, event_id)

    def _upload_file_sync(self, path: Path, filename: str, mime_type: str | None, event_id: str) -> str:
        credentials = service_account.Credentials.from_service_account_file(
            self._credentials_path,
            scopes=DRIVE_SCOPES,
        )
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        media = MediaFileUpload(str(path), mimetype=mime_type or "application/octet-stream", resumable=True)
        body = {"name": filename, "parents": [self._folder_id]}

        response = self._execute_with_retry(
            service.files().create(body=body, media_body=media, fields="id,webViewLink"),
            "drive_upload",
            event_id,
        )
        file_id = response["id"]

        self._execute_with_retry(
            service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                fields="id",
            ),
            "drive_permission",
            event_id,
        )

        link = response.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
        logger.info("event_id=%s drive_file_id=%s route=drive_link", event_id, file_id)
        return link

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
