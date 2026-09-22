from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from src.config import get_settings


class GoogleTokenError(Exception):
    """Raised when a Google ID token fails verification (bad signature, wrong audience, expired,
    malformed, ...) - the route layer turns this into a 401."""


def verify_google_id_token(token: str) -> dict:
    """Verify a Google Identity Services ID token (the `credential` a frontend <GoogleLogin/>
    returns) and return its claims (sub, email, email_verified, name, ...).

    Blocking: `verify_oauth2_token` does a network round-trip to fetch/cache Google's public certs
    the first time it's called. Callers inside an `async def` route must go through
    `starlette.concurrency.run_in_threadpool` rather than awaiting this directly, or it will block
    the event loop.
    """
    settings = get_settings()
    try:
        return google_id_token.verify_oauth2_token(
            token, google_requests.Request(), settings.google_oauth_client_id
        )
    except ValueError as exc:
        raise GoogleTokenError(str(exc)) from exc
