from __future__ import annotations

import json
import logging
from json import JSONDecodeError
from typing import Any
from urllib.parse import parse_qs

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from app.config import configure_logging, get_settings
from app.drive import DriveUploader
from app.router import SlackEventProcessor
from app.slack import verify_slack_signature
from app.store import EventStore
from app.telegram import TelegramClient


settings = get_settings()
configure_logging(settings)
logger = logging.getLogger(__name__)

app = FastAPI(title="Slack to Telegram Forwarder")
store = EventStore(settings.database_path)


@app.on_event("startup")
async def startup() -> None:
    store.initialize()
    missing = settings.missing_required(require_channel_ids=False)
    if missing:
        logger.warning("missing_required_env=%s", ",".join(missing))
    if not settings.slack_channel_ids:
        logger.warning("slack_channel_ids_empty=true automatic_event_forwarding_disabled=true")


@app.get("/health")
async def health() -> dict[str, object]:
    missing = settings.missing_required(require_channel_ids=False)
    return {
        "ok": not missing,
        "missing_env": missing,
        "automatic_event_forwarding_enabled": bool(settings.slack_channel_ids),
    }


@app.post("/slack/events")
async def slack_events(request: Request) -> dict[str, object]:
    body = await request.body()
    if not settings.slack_signing_secret:
        logger.error("slack_signing_secret_missing=true")
        raise HTTPException(status_code=503, detail="Slack signing secret is not configured")

    if not verify_slack_signature(request.headers, body, settings.slack_signing_secret):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    try:
        payload = json.loads(body)
    except JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    event_id = payload.get("event_id")
    if not event_id:
        logger.warning("slack_event_missing_event_id=true")
        return {"ok": True}

    if not store.record_event(event_id):
        logger.info("event_id=%s duplicate=true", event_id)
        return {"ok": True, "duplicate": True}

    missing = settings.missing_required()
    if missing:
        logger.error("event_id=%s cannot_process_missing_env=%s", event_id, ",".join(missing))
        return {"ok": True, "accepted": True, "processed": False}

    event = payload.get("event") or {}
    if not isinstance(event, dict):
        logger.warning("event_id=%s invalid_event_payload=true", event_id)
        return {"ok": True}

    telegram = TelegramClient(settings)
    drive = DriveUploader(settings)
    processor = SlackEventProcessor(settings, telegram, drive)

    try:
        await processor.process(event_id, event)
    except Exception:
        logger.exception("event_id=%s processing_failed=true", event_id)

    return {"ok": True}


@app.post("/slack/interactions")
async def slack_interactions(request: Request, background_tasks: BackgroundTasks) -> dict[str, object]:
    body = await request.body()
    if not settings.slack_signing_secret:
        logger.error("slack_signing_secret_missing=true")
        raise HTTPException(status_code=503, detail="Slack signing secret is not configured")

    if not verify_slack_signature(request.headers, body, settings.slack_signing_secret):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    form = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    payload_values = form.get("payload")
    if not payload_values:
        raise HTTPException(status_code=400, detail="Missing Slack interaction payload")

    try:
        payload = json.loads(payload_values[0])
    except JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid Slack interaction payload") from exc

    if payload.get("type") != "message_action":
        logger.info("slack_interaction_ignored_type=%s", payload.get("type"))
        return {"ok": True}

    callback_id = str(payload.get("callback_id") or "")
    if callback_id != settings.slack_message_shortcut_callback_id:
        logger.info("slack_interaction_ignored_callback_id=%s", callback_id)
        return {"ok": True}

    shortcut_id = _shortcut_dedup_id(payload, callback_id)
    if not store.record_event(shortcut_id):
        logger.info("event_id=%s duplicate=true", shortcut_id)
        return {"ok": True, "duplicate": True}

    missing = settings.missing_required(require_channel_ids=False)
    if missing:
        logger.error("event_id=%s cannot_process_missing_env=%s", shortcut_id, ",".join(missing))
        return {"ok": True, "accepted": True, "processed": False}

    background_tasks.add_task(process_message_shortcut, shortcut_id, payload)
    return {"ok": True, "accepted": True}


async def process_message_shortcut(shortcut_id: str, payload: dict[str, Any]) -> None:
    message = payload.get("message") or {}
    if not isinstance(message, dict):
        logger.warning("event_id=%s invalid_shortcut_message=true", shortcut_id)
        return

    channel_id = _shortcut_channel_id(payload)
    event = {
        **message,
        "type": "message",
        "channel": channel_id,
        "text": str(message.get("text") or ""),
    }

    telegram = TelegramClient(settings)
    drive = DriveUploader(settings)
    processor = SlackEventProcessor(settings, telegram, drive, enforce_channel_allowlist=False)

    try:
        await processor.process(shortcut_id, event)
    except Exception:
        logger.exception("event_id=%s shortcut_processing_failed=true", shortcut_id)


def _shortcut_channel_id(payload: dict[str, Any]) -> str:
    channel = payload.get("channel") or {}
    if isinstance(channel, dict):
        return str(channel.get("id") or "")
    return ""


def _shortcut_dedup_id(payload: dict[str, Any], callback_id: str) -> str:
    message = payload.get("message") or {}
    message_ts = ""
    if isinstance(message, dict):
        message_ts = str(message.get("ts") or "")
    trigger_id = str(payload.get("trigger_id") or "")
    channel_id = _shortcut_channel_id(payload)
    return f"shortcut:{callback_id}:{trigger_id}:{channel_id}:{message_ts}"
