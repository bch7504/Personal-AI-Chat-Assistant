import logging
import os
from datetime import UTC, datetime, timedelta

import httpx
import jwt
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from sqlalchemy import select

from src.auth.crypto import CredentialCryptoError, decrypt_secret, encrypt_secret
from src.config import get_settings
from src.db import session as db_session
from src.db.models import GoogleCalendarCredential

logger = logging.getLogger(__name__)

# Orbit only reads and writes events. It does not manage calendar sharing, ACLs, or
# calendar properties, so requesting the broader /auth/calendar scope would violate
# Google's least-privilege guidance and make public OAuth review unnecessarily broad.
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_STATE_PURPOSE = "calendar_oauth"


class CalendarNotConnectedError(Exception):
    pass


class OAuthStateError(Exception):
    pass


def _client_config() -> dict:
    settings = get_settings()
    if not settings.google_calendar_client_id or not settings.google_calendar_client_secret:
        raise RuntimeError("Google Calendar OAuth client is not configured")
    return {
        "web": {
            "client_id": settings.google_calendar_client_id,
            "client_secret": settings.google_calendar_client_secret,
            "auth_uri": _AUTH_URI,
            "token_uri": _TOKEN_URI,
        }
    }


def validate_configuration() -> None:
    """Fail before OAuth when credentials cannot be encrypted on this server."""
    _client_config()
    probe = "calendar-oauth-readiness"
    try:
        encrypted = encrypt_secret(probe)
        if decrypt_secret(encrypted) != probe:
            raise RuntimeError("credential encryption round-trip failed")
    except (CredentialCryptoError, RuntimeError, ValueError) as exc:
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY is invalid") from exc


def _build_flow(state: str | None = None) -> Flow:
    settings = get_settings()
    if settings.google_calendar_redirect_uri.startswith("http://"):
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    return Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=settings.google_calendar_redirect_uri,
        state=state,
        autogenerate_code_verifier=False,
    )


def make_oauth_state(user_id: str) -> str:
    settings = get_settings()
    return jwt.encode(
        {
            "sub": user_id,
            "purpose": _STATE_PURPOSE,
            "exp": datetime.now(UTC) + timedelta(minutes=10),
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )


def read_oauth_state(state: str) -> str:
    settings = get_settings()
    try:
        payload = jwt.decode(state, settings.secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("purpose") != _STATE_PURPOSE or not payload.get("sub"):
            raise OAuthStateError("OAuth state has the wrong purpose")
        return payload["sub"]
    except jwt.PyJWTError as exc:
        raise OAuthStateError("OAuth state is invalid or expired") from exc


def build_authorization_url(user_id: str) -> str:
    flow = _build_flow(state=make_oauth_state(user_id))
    # Do not merge grants previously issued to other OAuth clients in this Cloud project.
    # Orbit used to request the broader Calendar scope; combining that old grant with the
    # event-only scope makes oauthlib reject Google's token response as a scope mismatch.
    url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    return url


def exchange_code(code: str) -> Credentials:
    flow = _build_flow()
    flow.fetch_token(code=code)
    return flow.credentials


async def _row_for_user(db, user_id: str) -> GoogleCalendarCredential | None:
    return (
        await db.execute(select(GoogleCalendarCredential).where(GoogleCalendarCredential.user_id == user_id))
    ).scalar_one_or_none()


async def save_credentials(user_id: str, creds: Credentials, google_email: str = "") -> None:
    async with db_session.async_session_maker() as db:
        row = await _row_for_user(db, user_id)
        if row is None:
            if not creds.refresh_token:
                raise CalendarNotConnectedError("Google did not return a refresh token")
            row = GoogleCalendarCredential(user_id=user_id, refresh_token_enc=encrypt_secret(creds.refresh_token))
            db.add(row)
        elif creds.refresh_token:
            row.refresh_token_enc = encrypt_secret(creds.refresh_token)
            row.sync_token = None
        row.access_token_enc = encrypt_secret(creds.token) if creds.token else None
        row.token_expiry = creds.expiry.replace(tzinfo=UTC) if creds.expiry else None
        row.scopes = " ".join(creds.scopes or SCOPES)
        if google_email:
            row.google_email = google_email
        await db.commit()


async def get_connection_info(user_id: str) -> dict:
    async with db_session.async_session_maker() as db:
        row = await _row_for_user(db, user_id)
    return {
        "connected": row is not None,
        "google_email": row.google_email or None if row else None,
        "connected_at": row.created_at if row else None,
    }


async def disconnect(user_id: str) -> None:
    async with db_session.async_session_maker() as db:
        row = await _row_for_user(db, user_id)
        if row is None:
            return
        try:
            token = decrypt_secret(row.refresh_token_enc)
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post("https://oauth2.googleapis.com/revoke", data={"token": token})
        except Exception:  # noqa: BLE001 - local disconnect must still succeed
            logger.warning("Google token revoke failed; deleting local credential", exc_info=True)
        await db.delete(row)
        await db.commit()


async def get_credentials(user_id: str) -> Credentials:
    settings = get_settings()
    async with db_session.async_session_maker() as db:
        row = await _row_for_user(db, user_id)
        if row is None:
            raise CalendarNotConnectedError("Google Calendar is not connected")
        try:
            refresh_token = decrypt_secret(row.refresh_token_enc)
            access_token = decrypt_secret(row.access_token_enc) if row.access_token_enc else None
        except CredentialCryptoError as exc:
            raise CalendarNotConnectedError("Stored credential is unavailable") from exc
        expiry = row.token_expiry
        scopes = (row.scopes or " ".join(SCOPES)).split()

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=_TOKEN_URI,
        client_id=settings.google_calendar_client_id,
        client_secret=settings.google_calendar_client_secret,
        scopes=scopes,
        expiry=expiry.astimezone(UTC).replace(tzinfo=None) if expiry else None,
    )
    if not creds.valid:
        try:
            creds.refresh(GoogleRequest())
        except RefreshError as exc:
            await disconnect(user_id)
            raise CalendarNotConnectedError("Google Calendar access was revoked") from exc
        await save_credentials(user_id, creds)
    return creds


async def list_connected_user_ids() -> list[str]:
    async with db_session.async_session_maker() as db:
        return list((await db.execute(select(GoogleCalendarCredential.user_id))).scalars().all())


async def get_sync_token(user_id: str) -> str | None:
    async with db_session.async_session_maker() as db:
        row = await _row_for_user(db, user_id)
    return row.sync_token if row else None


async def set_sync_token(user_id: str, sync_token: str | None) -> None:
    async with db_session.async_session_maker() as db:
        row = await _row_for_user(db, user_id)
        if row is not None:
            row.sync_token = sync_token
            await db.commit()
