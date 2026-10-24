"""Auth-related env vars, validated once at import.

Importing this module is what makes the app fail fast at startup if a
required value is missing or malformed. Nothing here is hardcoded; every
value comes from the environment. Errors are plain RuntimeErrors with the
variable name in the message, so a bad .env is a one-line fix, not a
traceback hunt.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} environment variable is not set")
    return value


SESSION_SECRET = _required("SESSION_SECRET")
if len(SESSION_SECRET.encode("utf-8")) < 32:
    raise RuntimeError(
        "SESSION_SECRET must be at least 32 bytes. "
        "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
    )

GOOGLE_CLIENT_ID = _required("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _required("GOOGLE_CLIENT_SECRET")

# Comma- or whitespace-separated list. Comparison is case-insensitive.
_raw_allowed = _required("ALLOWED_EMAILS")
ALLOWED_EMAILS: frozenset[str] = frozenset(
    e.strip().lower() for e in _raw_allowed.replace(",", " ").split() if e.strip()
)
if not ALLOWED_EMAILS:
    raise RuntimeError("ALLOWED_EMAILS is set but contains no addresses")


# The one URL the app knows itself by. The Google OAuth redirect URI is
# derived from it, and so is whether cookies carry the Secure flag. Plain
# http is only accepted for localhost, so an insecure cookie can never be
# configured against a real hostname by accident.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _parse_app_base_url(raw: str) -> str:
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise RuntimeError(
            "APP_BASE_URL must be a full origin like http://localhost:8000 "
            f"(got {raw!r})"
        )
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise RuntimeError(
            "APP_BASE_URL must not include a path, query, or fragment "
            f"(got {raw!r})"
        )
    if parts.scheme == "http" and parts.hostname not in _LOCAL_HOSTS:
        raise RuntimeError(
            "APP_BASE_URL uses plain http on a host other than localhost; "
            "cookies would be sent without the Secure flag. Use https:// or a "
            f"localhost address (got {raw!r})"
        )
    return f"{parts.scheme}://{parts.netloc}"


APP_BASE_URL: str = _parse_app_base_url(_required("APP_BASE_URL").strip())
COOKIE_SECURE: bool = APP_BASE_URL.startswith("https://")
OAUTH_REDIRECT_URI: str = f"{APP_BASE_URL}/api/auth/google/callback"

# Where the browser lands after a successful login. Defaults to "/", which
# is the built app served by this process. Set it to the Angular dev
# server (http://localhost:4200/) while developing the frontend. Operator
# configuration, not user input, so it is used verbatim.
POST_LOGIN_REDIRECT: str = os.environ.get("POST_LOGIN_REDIRECT", "").strip() or "/"

SESSION_COOKIE_NAME = "honor_code_session"
SESSION_TTL_DAYS = 30

# Internal name used by Starlette's SessionMiddleware to hold the OAuth
# state parameter between /login and /callback. Distinct from the app
# session cookie above so the two don't get confused.
OAUTH_STATE_COOKIE_NAME = "honor_code_oauth"
