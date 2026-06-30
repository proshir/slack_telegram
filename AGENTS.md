# AGENTS.md

## Project goal

Build a small Python service that forwards selected Slack channel activity (messages) to Telegram.

Behavior:
- Slack text messages are sent directly to Telegram.
- PDFs and normal files are sent directly to Telegram when possible.
- Videos are uploaded to Google Drive, then a Google Drive link is sent to Telegram.
- If any file is too large for Telegram, upload it to Google Drive and send a link instead.
- Do not expose Slack private file URLs directly in Telegram.

## Tech stack

Use:
- Python 3.12
- FastAPI for Slack webhooks
- httpx for HTTP requests
- python-telegram-bot or direct Telegram Bot API calls
- Google Drive API for video uploads
- SQLite for deduplication/state

Avoid:
- heavy frameworks
- Celery unless clearly needed
- unnecessary cloud services
- storing secrets in code
- tests 

## Required environment variables
use python-dotenv or similar to load from .env file. use load_dotenv(override=True).

## Implementation rules

- Verify Slack request signatures.
- Handle Slack URL verification challenge.
- Ignore bot messages to avoid loops.
- Deduplicate Slack events by event_id.
- Download Slack private files using the Slack bot token.
- Never log secrets or full tokens.
- Log useful event IDs, file IDs, MIME types, and routing decisions.
- Add clear error handling and retry only where safe.
- Keep the first version simple and deployable with Docker Compose.

## Done means

A change is done only when:
- the app starts locally
- environment variables are documented
- Dockerfile and docker-compose.yml still work
