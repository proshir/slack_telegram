# Slack to Telegram Forwarder

Small FastAPI service that forwards selected Slack channel activity to Telegram.

## Behavior

- Verifies Slack request signatures.
- Handles Slack URL verification challenges.
- Ignores bot messages and duplicate Slack `event_id` values.
- Filters Slack events by `SLACK_CHANNEL_IDS`.
- Sends Slack text messages to Telegram.
- Sends forwarded or shared Slack messages to Telegram, including nested text and files.
- Downloads Slack private files with the Slack bot token before forwarding.
- Sends normal files and images to Telegram when they fit within `TELEGRAM_MAX_UPLOAD_MB`.
- Uploads videos and oversized files to Google Drive with restricted access, then sends the Drive link to Telegram.
- Never posts Slack private file URLs to Telegram.

## Configuration

Copy `.env.example` to `.env` and fill in the values.

Do not commit `.env`, Slack tokens, Telegram tokens, OAuth client JSON files, or OAuth token JSON files.

### Environment Variables

| Variable | Required | How to get it |
| --- | --- | --- |
| `SLACK_SIGNING_SECRET` | Yes | Open <https://api.slack.com/apps>, select your Slack app, go to **Basic Information**, then copy **Signing Secret** from **App Credentials**. |
| `SLACK_BOT_TOKEN` | Yes | In the same Slack app, go to **OAuth & Permissions**, add bot scopes, install or reinstall the app to the workspace, then copy **Bot User OAuth Token**. It starts with `xoxb-`. |
| `SLACK_CHANNEL_IDS` | Events only | Required only for automatic Event Subscriptions forwarding. In Slack, open each source channel, click the channel name, open channel details, and copy the channel ID. Put multiple IDs in `.env` separated by commas, with no spaces required. Leave empty if you only use the manual message shortcut. |
| `SLACK_MESSAGE_SHORTCUT_CALLBACK_ID` | No | Use this as the callback ID when creating the Slack message shortcut. Default is `send_to_telegram`. |
| `TELEGRAM_BOT_TOKEN` | Yes | In Telegram, message `@BotFather`, run `/newbot`, follow the prompts, then copy the token BotFather returns. For an existing bot, use `/mybots`, select the bot, then use **API Token**. |
| `TELEGRAM_CHAT_ID` | Yes | Add the bot to the destination chat or channel, send a test message, then call `https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates` and copy `message.chat.id` or `channel_post.chat.id`. |
| `GOOGLE_OAUTH_TOKEN` | Yes | Path to the generated OAuth user token JSON. For Compose, use `/app/data/google-oauth-token.json` so refreshed tokens can be saved in the writable data volume. |
| `GOOGLE_DRIVE_FOLDER_ID` | Yes | In Google Drive, create or open the destination folder, then copy the folder ID from the folder URL. |
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

GOOGLE_OAUTH_TOKEN=/app/data/google-oauth-token.json
GOOGLE_DRIVE_FOLDER_ID=1AbCdEfGhIjKlMnOpQrStUvWxYz

SLACK_MESSAGE_SHORTCUT_CALLBACK_ID=send_to_telegram
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

For Docker Compose, put the Google OAuth client JSON under `./secrets`; the generated OAuth token lives under `./data`.

## Slack Setup

1. Create a Slack app and add a bot token with permission to read files and messages in the channels you want to forward.
2. Subscribe the app to message events for the relevant channel types. Forwarded messages, message shares, file shares, images, and videos are handled from the message event payload.
3. Set the Events API request URL to `https://your-domain.example/slack/events`.
4. Invite the bot to each allowed Slack channel.
5. Put those channel IDs in `SLACK_CHANNEL_IDS`.

For Slack Connect channels or app-originated shares, Slack may send a lightweight file object before exposing the private download URL. Keep the `files:read` scope enabled and make sure the bot can see the source channel; the service will call Slack `files.info` with the file ID when it needs to hydrate the file before downloading it.

## Slack Message Shortcut Setup

Use this when you want to right-click a Slack message and manually send that selected message to Telegram, without copying or forwarding it into a watched channel.

1. Open your Slack app at <https://api.slack.com/apps>.
2. Go to **Interactivity & Shortcuts**.
3. Turn **Interactivity** on.
4. Set **Request URL** to:

```text
https://your-domain.example/slack/interactions
```

5. In the same page, create a new shortcut.
6. Choose **On messages** as the shortcut type.
7. Set the shortcut name to something users will see, for example:

```text
Send to Telegram
```

8. Set **Callback ID** to the same value as `SLACK_MESSAGE_SHORTCUT_CALLBACK_ID`:

```text
send_to_telegram
```

9. Save the shortcut.
10. Reinstall the app to the workspace if Slack asks you to.

After that, users can open a message menu in Slack, choose **Send to Telegram**, and the app will send that selected message to Telegram. This manual shortcut does not enforce `SLACK_CHANNEL_IDS`; the user intentionally selected the exact message to send.

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

This app uploads to a personal **My Drive** folder using your Google account OAuth token, including Google One storage such as 3 TB plans.

1. Open Google Cloud Console at <https://console.cloud.google.com/>.
2. Select or create the Google Cloud project you want to use.
3. Enable the Google Drive API for that project.
4. Open **APIs & Services** > **OAuth consent screen** and configure the app for your account.
5. Open **APIs & Services** > **Credentials**.
6. Click **Create credentials** > **OAuth client ID**.
7. Choose **Desktop app**.
8. Download the client JSON and save it as `./secrets/google-oauth-client.json`.
9. Generate the OAuth token once and let the helper create or reuse the upload folder:

```bash
python -m app.google_oauth_auth \
  --client-secrets ./secrets/google-oauth-client.json \
  --token ./data/google-oauth-token.json \
  --create-folder "Slack Telegram Uploads"
```

If the browser cannot open automatically, add `--no-browser`, open the printed URL, and complete the login.

10. Copy the printed `GOOGLE_DRIVE_FOLDER_ID`. If you rerun the command later with the same folder name, the helper reuses the existing folder when it can see it.
11. In `.env`, set:

```env
GOOGLE_OAUTH_TOKEN=/app/data/google-oauth-token.json
GOOGLE_DRIVE_FOLDER_ID=1AbCdEfGhIjKlMnOpQrStUvWxYz
```

The app requests the narrower Google Drive `drive.file` scope. The downloaded OAuth client JSON is only needed for the one-time token generation command. The running Docker container uses the generated `GOOGLE_OAUTH_TOKEN`; keep that file private. In Docker Compose, `./data` is mounted writable so token refreshes can be persisted, while `./secrets` remains read-only for the downloaded OAuth client JSON.

Uploaded Drive files keep Google Drive's default restricted access. Telegram receives the Drive link, but only Google accounts that already have access to the file or destination folder can open it.

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

Run it with your local `.env`, writable data directory, and read-only OAuth setup files mounted:

```bash
docker run --env-file .env \
  -p 8000:8000 \
  -v "$PWD/data:/app/data" \
  -v "$PWD/secrets:/app/secrets:ro" \
  ghcr.io/OWNER/REPOSITORY:latest
```
