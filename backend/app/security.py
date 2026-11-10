"""Hashing of proxy keys and at-rest encryption of provider API keys."""
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

KEY_PREFIX = "sk-proxy-"


def generate_proxy_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_proxy_key(key: str) -> str:
    # Keys are 256-bit random, so a peppered SHA-256 is sufficient (no need for a slow KDF).
    pepper = get_settings().key_pepper.encode()
    return hmac.new(pepper, key.encode(), hashlib.sha256).hexdigest()


def key_display_prefix(key: str) -> str:
    return key[: len(KEY_PREFIX) + 4]


def _fernet() -> Fernet:
    k = get_settings().secret_key
    if not k:
        raise RuntimeError("PROXY_SECRET_KEY is not set (generate one with: python -m app.security)")
    return Fernet(k.encode())


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


if __name__ == "__main__":
    print(Fernet.generate_key().decode())
