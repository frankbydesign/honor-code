"""Symmetric encryption for OAuth tokens we'll persist later.

Reads ENCRYPTION_KEY (a Fernet key, i.e. the output of
`Fernet.generate_key()`) once at import. The key never leaves memory:
do not log it, do not write it to disk.

We don't store any tokens yet, but Gmail and Calendar will need this
soon, and putting the helper in place now keeps the pattern consistent.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


def _load_key() -> bytes:
    raw = os.environ.get("ENCRYPTION_KEY")
    if not raw:
        raise RuntimeError(
            "ENCRYPTION_KEY environment variable is not set. "
            "Generate one with: python -c "
            "'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    key = raw.encode("utf-8")
    try:
        Fernet(key)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            "ENCRYPTION_KEY is not a valid Fernet key. "
            "It must be 32 url-safe base64-encoded bytes."
        ) from exc
    return key


_fernet = Fernet(_load_key())


def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("could not decrypt token") from exc
