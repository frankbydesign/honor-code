"""Set the env vars `app.*` modules require at import time.

These are populated *before* any test module imports anything from
`app.*`, so the import-time validators in `app.auth.config`,
`app.security.token_crypto`, and `app.db.session` see a working
configuration. Tests that need a different config (e.g. the startup
validator's negative cases) run in subprocesses.
"""

from __future__ import annotations

import os
import secrets

from cryptography.fernet import Fernet


_DEFAULTS = {
    "SESSION_SECRET": secrets.token_urlsafe(48),
    "GOOGLE_CLIENT_ID": "test-client-id",
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
    "ALLOWED_EMAILS": "test@example.com",
    "FRONTEND_ORIGINS": "https://app.example.com",
    "FRONTEND_ORIGINS_PATTERNS": "https://honor-code-*-cpdigital.vercel.app",
    "ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
}

for key, value in _DEFAULTS.items():
    os.environ.setdefault(key, value)
