"""One-time, developer-run script to authorize this app against a Google account's
Calendar and store the resulting refresh token to disk.

Usage:
    1. Create OAuth 2.0 credentials (Desktop app) in the Google Cloud Console and
       download the client secrets as GOOGLE_CREDENTIALS_PATH (see .env.example).
    2. Run: python scripts/google_oauth_setup.py
       This opens a local browser window for you to sign in and grant access.
    3. The resulting token is written to GOOGLE_TOKEN_PATH. The running FastAPI
       server only ever refreshes this token - it never launches an interactive
       browser flow mid-request.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

from src.config import get_settings  # noqa: E402

_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def main() -> None:
    settings = get_settings()
    flow = InstalledAppFlow.from_client_secrets_file(settings.google_credentials_path, _SCOPES)
    creds = flow.run_local_server(port=0)

    token_path = Path(settings.google_token_path)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    print(f"Token written to {token_path}")


if __name__ == "__main__":
    main()
