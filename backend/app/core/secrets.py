"""Envelope encryption for connector credentials (AES-256-GCM).

The key is derived from CREDENTIAL_ENCRYPTION_KEY when configured, otherwise
from JWT_SECRET. Production deployments should provide an independent,
externally-managed key and rotate it through a secret manager.
"""
from __future__ import annotations

import base64
import hashlib
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings


def _key() -> bytes:
    material = os.getenv("CREDENTIAL_ENCRYPTION_KEY") or settings.credential_encryption_key or settings.jwt_secret
    return hashlib.sha256(("twin-credential-v1:" + material).encode()).digest()


def encrypt_secret(plaintext: str) -> tuple[str, str]:
    aes = AESGCM(_key())
    nonce = os.urandom(12)
    ciphertext = aes.encrypt(nonce, plaintext.encode(), b"business-twin-credential")
    return (
        base64.b64encode(ciphertext).decode(),
        base64.b64encode(nonce).decode(),
    )


def decrypt_secret(ciphertext: str, nonce: str) -> str:
    aes = AESGCM(_key())
    return aes.decrypt(
        base64.b64decode(nonce), base64.b64decode(ciphertext), b"business-twin-credential"
    ).decode()


def key_hint(plaintext: str) -> str:
    return f"••••{plaintext[-4:]}" if len(plaintext) >= 4 else "••••"
