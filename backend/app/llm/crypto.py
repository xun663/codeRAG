"""Fernet symmetric encryption for LLM API keys at rest.

Keys are stored in `llm_profiles.api_key_encrypted` as Fernet ciphertext rather
than plaintext. The Fernet key is derived from `settings.fernet_key` if set,
otherwise deterministically from `settings.secret_key`.
"""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    raw = settings.effective_fernet_key
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext secret. Empty input passes through as empty."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet ciphertext. Empty input passes through as empty."""
    if not ciphertext:
        return ""
    return _fernet().decrypt(ciphertext.encode()).decode()
