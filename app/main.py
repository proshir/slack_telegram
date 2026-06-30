from __future__ import annotations

import json
import logging
from json import JSONDecodeError

from fastapi import FastAPI, HTTPException, Request

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
    missing = settings.missing_required()
    if missing:
        logger.warning("missing_required_env=%s", ",".join(missing))


@app.get("/health")
async def health() -> dict[str, object]:
    missing = settings.missing_required()
    return {"ok": not missing, "missing_env": missing}


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

