from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


REQUIRED_ENV = (
    "SLACK_SIGNING_SECRET",
    "SLACK_BOT_TOKEN",
    "SLACK_CHANNEL_IDS",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_DRIVE_FOLDER_ID",
)


def _csv_set(value: str) -> set[str]:
    return {part.strip() for part in value.split(",") if part.strip()}


@dataclass(frozen=True)
class Settings:
    slack_signing_secret: str
    slack_bot_token: str
    slack_channel_ids: set[str]
    telegram_bot_token: str
    telegram_chat_id: str
    google_application_credentials: str
    google_drive_folder_id: str
    slack_message_shortcut_callback_id: str
    database_path: Path
    telegram_max_upload_mb: int
    log_level: str
    request_timeout_seconds: float

    @property
    def telegram_max_upload_bytes(self) -> int:
        return self.telegram_max_upload_mb * 1024 * 1024

    def missing_required(self, require_channel_ids: bool = True) -> list[str]:
        missing: list[str] = []
        if not self.slack_signing_secret:
            missing.append("SLACK_SIGNING_SECRET")
        if not self.slack_bot_token:
            missing.append("SLACK_BOT_TOKEN")
        if require_channel_ids and not self.slack_channel_ids:
            missing.append("SLACK_CHANNEL_IDS")
        if not self.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.telegram_chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        if not self.google_application_credentials:
            missing.append("GOOGLE_APPLICATION_CREDENTIALS")
        if not self.google_drive_folder_id:
            missing.append("GOOGLE_DRIVE_FOLDER_ID")
        return missing


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(override=True)
    return Settings(
        slack_signing_secret=os.getenv("SLACK_SIGNING_SECRET", ""),
        slack_bot_token=os.getenv("SLACK_BOT_TOKEN", ""),
        slack_channel_ids=_csv_set(os.getenv("SLACK_CHANNEL_IDS", "")),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        google_application_credentials=os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""),
        google_drive_folder_id=os.getenv("GOOGLE_DRIVE_FOLDER_ID", ""),
        slack_message_shortcut_callback_id=os.getenv("SLACK_MESSAGE_SHORTCUT_CALLBACK_ID", "send_to_telegram"),
        database_path=Path(os.getenv("DATABASE_PATH", "./data/state.db")),
        telegram_max_upload_mb=int(os.getenv("TELEGRAM_MAX_UPLOAD_MB", "50")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")),
    )


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
