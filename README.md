# Slack to Telegram Forwarder

Small FastAPI service that forwards selected Slack channel activity to Telegram.

## Behavior

- Verifies Slack request signatures.
- Handles Slack URL verification challenges.
- Ignores bot messages and duplicate Slack `event_id` values.
- Filters Slack events by `SLACK_CHANNEL_IDS`.
- Sends Slack text messages to Telegram.
- Downloads Slack private files with the Slack bot token before forwarding.
- Sends normal files to Telegram when they fit within `TELEGRAM_MAX_UPLOAD_MB`.
- Uploads videos and oversized files to Google Drive, makes them readable by anyone with the link, and sends the Drive link to Telegram.
- Never posts Slack private file URLs to Telegram.

## Configuration

Copy `.env.example` to `.env` and fill in the values.

Do not commit `.env`, Slack tokens, Telegram tokens, or Google service account JSON files.

### Environment Variables

| Variable | Required | How to get it |
| --- | --- | --- |
| `SLACK_SIGNING_SECRET` | Yes | Open <https://api.slack.com/apps>, select your Slack app, go to **Basic Information**, then copy **Signing Secret** from **App Credentials**. |
| `SLACK_BOT_TOKEN` | Yes | In the same Slack app, go to **OAuth & Permissions**, add bot scopes, install or reinstall the app to the workspace, then copy **Bot User OAuth Token**. It starts with `xoxb-`. |
| `SLACK_CHANNEL_IDS` | Yes | In Slack, open each source channel, click the channel name, open channel details, and copy the channel ID. Put multiple IDs in `.env` separated by commas, with no spaces required. |
| `TELEGRAM_BOT_TOKEN` | Yes | In Telegram, message `@BotFather`, run `/newbot`, follow the prompts, then copy the token BotFather returns. For an existing bot, use `/mybots`, select the bot, then use **API Token**. |
| `TELEGRAM_CHAT_ID` | Yes | Add the bot to the destination chat or channel, send a test message, then call `https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates` and copy `message.chat.id` or `channel_post.chat.id`. |
| `GOOGLE_APPLICATION_CREDENTIALS` | Yes | In Google Cloud, create a service account, create a JSON key for it, save the JSON file locally, and set this variable to the path inside the runtime container. For Compose, use `/app/secrets/google-service-account.json`. |
| `GOOGLE_DRIVE_FOLDER_ID` | Yes | In Google Drive, create or open the destination folder, share it with the service account email, then copy the folder ID from the folder URL. |
| `DATABASE_PATH` | No | Set this to the SQLite file path where deduplication state should be stored. |
| `TELEGRAM_MAX_UPLOAD_MB` | No | Set this to the max file size the app should attempt to send directly to Telegram before falling back to Google Drive. Default is `50`. |
| `LOG_LEVEL` | No | Set to `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. Default is `INFO`. |
| `REQUEST_TIMEOUT_SECONDS` | No | Set to the HTTP timeout, in seconds, for Slack downloads and Telegram calls. Default is `30`. |

Example:

```env
SLACK_SIGNING_SECRET=your-slack-signing-secret
SLACK_BOT_TOKEN=xoxb-your-slack-bot-token
SLACK_CHANNEL_IDS=C0123456789,C9876543210

TELEGRAM_BOT_TOKEN=123456789:telegram-bot-token
TELEGRAM_CHAT_ID=-1001234567890

GOOGLE_APPLICATION_CREDENTIALS=/app/secrets/google-service-account.json
GOOGLE_DRIVE_FOLDER_ID=1AbCdEfGhIjKlMnOpQrStUvWxYz

DATABASE_PATH=./data/state.db
TELEGRAM_MAX_UPLOAD_MB=50
LOG_LEVEL=INFO
REQUEST_TIMEOUT_SECONDS=30
```

### Slack Values

1. Go to <https://api.slack.com/apps>.
2. Create a new app or open the existing app.
3. Open **Basic Information**.
4. Under **App Credentials**, copy **Signing Secret** into `SLACK_SIGNING_SECRET`.
5. Open **OAuth & Permissions**.
6. Under **Scopes**, add the bot scopes needed for the channel types you will read. Typical first-version scopes are `files:read`, `channels:history`, and `groups:history`. Add `im:history` or `mpim:history` only if you intentionally forward direct messages or multi-person DMs.
7. Click **Install to Workspace** or **Reinstall to Workspace** after changing scopes.
8. Copy **Bot User OAuth Token** into `SLACK_BOT_TOKEN`.
9. In Slack, open each source channel and copy the channel ID from the channel details. Put those IDs into `SLACK_CHANNEL_IDS`, comma-separated:

```env
SLACK_CHANNEL_IDS=C0123456789,C9876543210
```

For Docker Compose, put the Google service account JSON at `./secrets/google-service-account.json` or update `GOOGLE_APPLICATION_CREDENTIALS` and the volume mount together.

## Slack Setup

1. Create a Slack app and add a bot token with permission to read files and messages in the channels you want to forward.
2. Subscribe the app to message events for the relevant channel types.
3. Set the Events API request URL to `https://your-domain.example/slack/events`.
4. Invite the bot to each allowed Slack channel.
5. Put those channel IDs in `SLACK_CHANNEL_IDS`.

## Telegram Setup

1. Create a bot with BotFather.
2. Add the bot to the destination chat or channel.
3. Put the bot token in `TELEGRAM_BOT_TOKEN`.
4. Send one test message in the destination chat or channel after the bot is added.
5. Open this URL in a browser, replacing `YOUR_BOT_TOKEN` with the real token:

```text
https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
```

Example:

```text
https://api.telegram.org/bot123456789:AAExampleToken/getUpdates
```

6. In the JSON response, find the latest update and copy `message.chat.id` into `TELEGRAM_CHAT_ID`.

For a group or supergroup, the value usually starts with `-`. For a channel, make the bot an admin, post a message in the channel, then use the same `getUpdates` URL and copy `channel_post.chat.id`.

Example response shape:

```json
{
  "ok": true,
  "result": [
    {
      "message": {
        "chat": {
          "id": -1001234567890,
          "title": "Forwarded Slack Alerts"
        }
      }
    }
  ]
}
```

Set:

```env
TELEGRAM_CHAT_ID=-1001234567890
```

## Google Drive Setup

1. Open Google Cloud Console at <https://console.cloud.google.com/>.
2. Select or create the Google Cloud project you want to use.
3. Enable the Google Drive API for that project.
4. Open **IAM & Admin** > **Service Accounts**.
5. Click **Create service account**.
6. Give it a name such as `slack-telegram-drive-uploader`, then finish creation.
7. Open the service account, go to **Keys**, click **Add key** > **Create new key**, choose **JSON**, and download the file.
8. Save that JSON file as `./secrets/google-service-account.json`.
9. In `.env`, set:

```env
GOOGLE_APPLICATION_CREDENTIALS=/app/secrets/google-service-account.json
```

10. Open Google Drive and create or select the destination folder for uploaded videos and oversized files.
11. Share that folder with the service account email address. The email is inside the JSON file as `client_email`, and looks like `name@project-id.iam.gserviceaccount.com`.
12. Copy the folder ID from the browser URL. For this URL:

```text
https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz
```

The folder ID is:

```text
1AbCdEfGhIjKlMnOpQrStUvWxYz
```

13. In `.env`, set:

```env
GOOGLE_DRIVE_FOLDER_ID=1AbCdEfGhIjKlMnOpQrStUvWxYz
```

## Local Run

For local `uvicorn`, keep `DATABASE_PATH=./data/state.db` in `.env`. Do not use `/app/data/state.db` unless you are running inside the Docker container; on the host machine that path points to `/app`, and normal users usually cannot create it.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

## Docker Compose

```bash
docker compose up --build
```

The app listens on port `8000`.

To run a published registry image with Docker Compose instead of building locally, set `DOCKER_IMAGE` first:

```bash
DOCKER_IMAGE=ghcr.io/OWNER/REPOSITORY:latest docker compose up -d
```

## GitHub CI/CD

This repo includes a GitHub Actions workflow at `.github/workflows/docker-publish.yml`.

The workflow:

- Builds the Docker image for pull requests, without pushing it.
- Builds and pushes the Docker image to GitHub Container Registry on pushes to `main` or `master`.
- Builds and pushes version tags like `v1.0.0`.
- Can be run manually from the **Actions** tab with **Run workflow**.

The pushed image name is:

```text
ghcr.io/OWNER/REPOSITORY
```

For this repo on GitHub, replace `OWNER` and `REPOSITORY` with the actual GitHub owner and repository name. The workflow lowercases the image name automatically because container registry names must be lowercase.

Tags created by the workflow include:

- `latest` for the default branch
- The branch name, such as `main`
- The short commit SHA, such as `sha-abc1234`
- The version tag, such as `1.0.0`, when pushing `v1.0.0`

Before the first run, check GitHub repository settings:

1. Open the GitHub repository.
2. Go to **Settings** > **Actions** > **General**.
3. Under **Workflow permissions**, select **Read and write permissions**.
4. Save the setting.

No registry username/password secret is needed for GitHub Container Registry. The workflow uses the built-in `GITHUB_TOKEN` with `packages: write` permission.

After the workflow runs, pull the image with:

```bash
docker pull ghcr.io/OWNER/REPOSITORY:latest
```

Run it with your local `.env`, data directory, and Google credentials mounted:

```bash
docker run --env-file .env \
  -p 8000:8000 \
  -v "$PWD/data:/app/data" \
  -v "$PWD/secrets:/app/secrets:ro" \
  ghcr.io/OWNER/REPOSITORY:latest
```
