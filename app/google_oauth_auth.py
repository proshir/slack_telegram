from __future__ import annotations

import argparse
import logging
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.drive import DRIVE_SCOPES


logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Google Drive OAuth token for this app.")
    parser.add_argument(
        "--client-secrets",
        default="./secrets/google-oauth-client.json",
        help="Path to the OAuth desktop client JSON downloaded from Google Cloud.",
    )
    parser.add_argument(
        "--token",
        default="./secrets/google-oauth-token.json",
        help="Path where the generated OAuth token JSON should be saved.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Local callback host.")
    parser.add_argument("--port", type=int, default=8080, help="Local callback port.")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the authorization URL instead of opening a browser automatically.",
    )
    parser.add_argument(
        "--create-folder",
        default="",
        help="Create a Google Drive folder with this name after authorization and print its folder ID.",
    )
    args = parser.parse_args()

    client_secrets_path = Path(args.client_secrets)
    token_path = Path(args.token)
    if not client_secrets_path.exists():
        raise SystemExit(f"OAuth client secrets file not found: {client_secrets_path}")

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), scopes=DRIVE_SCOPES)
    credentials = flow.run_local_server(
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
        authorization_prompt_message="Open this URL to authorize Google Drive access:\n{url}\n",
        success_message="Google Drive authorization complete. You can close this browser tab.",
    )

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    print(f"Saved OAuth token to {token_path}")

    if args.create_folder:
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        folder = (
            service.files()
            .create(
                body={"name": args.create_folder, "mimeType": "application/vnd.google-apps.folder"},
                fields="id,webViewLink",
            )
            .execute()
        )
        print(f"Created Google Drive folder: {folder.get('webViewLink')}")
        print(f"Set GOOGLE_DRIVE_FOLDER_ID={folder['id']}")


if __name__ == "__main__":
    main()
