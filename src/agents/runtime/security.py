from __future__ import annotations

import hashlib
import hmac
import time

SIGNATURE_HEADER = "X-Orbit-Signature"
TIMESTAMP_HEADER = "X-Orbit-Timestamp"


def sign_runtime_body(body: bytes, *, secret: str, timestamp: int) -> str:
    message = str(timestamp).encode("ascii") + b"." + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_runtime_signature(
    body: bytes,
    *,
    secret: str,
    timestamp_text: str | None,
    signature: str | None,
    max_age_seconds: int,
    now: int | None = None,
) -> bool:
    if not secret or not timestamp_text or not signature:
        return False
    try:
        timestamp = int(timestamp_text)
    except ValueError:
        return False
    checked_at = int(time.time()) if now is None else now
    if abs(checked_at - timestamp) > max_age_seconds:
        return False
    expected = sign_runtime_body(body, secret=secret, timestamp=timestamp)
    return hmac.compare_digest(expected, signature)
