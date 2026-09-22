from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from src.config import get_settings


class CredentialCryptoError(Exception):
    pass


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().credential_encryption_key
    if not key:
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY is not configured; generate a persistent Fernet key")
    return Fernet(key.encode())


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise CredentialCryptoError("Stored credential could not be decrypted") from exc
