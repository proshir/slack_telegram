from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Mapping


IGNORED_SUBTYPES = {
    "bot_message",
    "message_changed",
    "message_deleted",
    "message_replied",
}


def verify_slack_signature(headers: Mapping[str, str], body: bytes, signing_secret: str) -> bool:
    timestamp = headers.get("x-slack-request-timestamp")
    signature = headers.get("x-slack-signature")
    if not timestamp or not signature:
        return False

    try:
        request_ts = int(timestamp)
    except ValueError:
        return False

    if abs(time.time() - request_ts) > 60 * 5:
        return False

    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    digest = hmac.new(signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature)


def is_message_event(event: dict[str, Any]) -> bool:
    return event.get("type") == "message"


def is_bot_message(event: dict[str, Any]) -> bool:
    subtype = event.get("subtype")
    return bool(event.get("bot_id") or subtype in IGNORED_SUBTYPES)

