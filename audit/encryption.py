"""
Audit log envelope encryption (tech direction Section 2).

query_text and generated_answer are encrypted at the application layer before
being written to the database, using a Fernet symmetric key.

Setup:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    Add to .env:  AUDIT_ENCRYPTION_KEY=<output>

If AUDIT_ENCRYPTION_KEY is not set, encrypt/decrypt are no-ops (plaintext).
This lets the table exist before the key is configured, and makes the key
optional in dev while required in prod.

KMS upgrade path: replace _fernet() with a KMS data-key envelope:
    1. Call KMS GenerateDataKey -> get plaintext key + encrypted key blob
    2. Encrypt with plaintext key (Fernet)
    3. Store encrypted blob alongside ciphertext
    4. On decrypt: call KMS Decrypt to recover plaintext key, then Fernet decrypt
"""

import os
from functools import lru_cache
from typing import Optional

_KEY_ENV = "AUDIT_ENCRYPTION_KEY"


@lru_cache(maxsize=1)
def _fernet():
    key = os.getenv(_KEY_ENV, "").strip()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:
        raise RuntimeError(
            f"AUDIT_ENCRYPTION_KEY is set but invalid: {exc}. "
            "Generate a key with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        ) from exc


def encrypt(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a string. Returns ciphertext prefixed with 'enc:' so we can detect it on read."""
    if plaintext is None:
        return None
    f = _fernet()
    if f is None:
        return plaintext
    return "enc:" + f.encrypt(plaintext.encode()).decode()


def decrypt(value: Optional[str]) -> Optional[str]:
    """Decrypt a value previously returned by encrypt(). Pass-through if not encrypted."""
    if value is None:
        return None
    if not value.startswith("enc:"):
        return value  # stored before encryption was enabled — return as-is
    f = _fernet()
    if f is None:
        return value  # key removed after data was encrypted — return raw
    return f.decrypt(value[4:].encode()).decode()
