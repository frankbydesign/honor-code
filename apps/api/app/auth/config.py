"""Auth-related env vars, validated once at import.

Importing this module is what makes the app fail fast at startup if a
required secret is missing. Don't hardcode any of these values; they
must come from the environment.
"""

from __future__ import annotations

import os
import re

from app.auth.origins import compile_patterns, parse_patterns_env


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

# If set, used verbatim as the Google OAuth redirect target. Otherwise
# we derive it from the incoming request via url_for(). The env var is
# the safer choice on Railway (proxy headers can lie).
OAUTH_REDIRECT_URI: str | None = os.environ.get("OAUTH_REDIRECT_URI") or None

# Frontend origins permitted to (a) make credentialed CORS requests and
# (b) be used as the post-login `?next=` redirect target. Comma- or
# whitespace-separated. Each entry must be a full origin
# (scheme://host[:port]) with no path or trailing slash.
_raw_frontend_origins = _required("FRONTEND_ORIGINS")
FRONTEND_ORIGINS: tuple[str, ...] = tuple(
    o.strip().rstrip("/")
    for o in _raw_frontend_origins.replace(",", " ").split()
    if o.strip()
)
if not FRONTEND_ORIGINS:
    raise RuntimeError("FRONTEND_ORIGINS is set but contains no origins")
for _origin in FRONTEND_ORIGINS:
    if "://" not in _origin:
        raise RuntimeError(
            f"FRONTEND_ORIGINS entry {_origin!r} must be a full origin "
            "like https://example.com (no path, no trailing slash)"
        )

# Glob patterns layered on top of the FRONTEND_ORIGINS exact list. `*`
# is the only wildcard. Used to allow Vercel Preview URLs whose host
# names change per deployment. Empty/unset means "no patterns" — the
# system then behaves identically to the pre-pattern config.
_raw_frontend_origin_patterns = os.environ.get("FRONTEND_ORIGINS_PATTERNS", "")
FRONTEND_ORIGINS_PATTERNS: tuple[str, ...] = parse_patterns_env(
    _raw_frontend_origin_patterns
)
FRONTEND_ORIGINS_PATTERN_REGEX: re.Pattern[str] | None = compile_patterns(
    FRONTEND_ORIGINS_PATTERNS
)

SESSION_COOKIE_NAME = "honor_code_session"
SESSION_TTL_DAYS = 30

# Internal name used by Starlette's SessionMiddleware to hold the OAuth
# state parameter between /login and /callback. Distinct from the app
# session cookie above so the two don't get confused.
OAUTH_STATE_COOKIE_NAME = "honor_code_oauth"
