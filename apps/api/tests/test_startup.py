"""The app must refuse to start on a bad configuration, with a readable error.

app.auth.config validates at import, and other modules cache its values, so
each case runs `import app.auth.config` in a fresh subprocess with a modified
environment. Plain sync tests; pytest-asyncio's auto mode leaves them alone.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

_IMPORT_CONFIG = textwrap.dedent(
    """
    import sys
    try:
        import app.auth.config as c
    except RuntimeError as exc:
        sys.stderr.write(str(exc))
        sys.exit(2)
    sys.stdout.write(f"COOKIE_SECURE={c.COOKIE_SECURE} REDIRECT={c.OAUTH_REDIRECT_URI}")
    sys.exit(0)
    """
)


def _run(**env_overrides: str | None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(
        [sys.executable, "-c", _IMPORT_CONFIG],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _assert_refused(result: subprocess.CompletedProcess[str], *needles: str) -> None:
    assert result.returncode == 2, result.stdout + result.stderr
    for needle in needles:
        assert needle in result.stderr, result.stderr
    assert "Traceback" not in result.stderr


def _assert_accepted(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def test_refuses_missing_app_base_url():
    _assert_refused(_run(APP_BASE_URL=None), "APP_BASE_URL")


def test_refuses_http_base_url_on_non_localhost_host():
    _assert_refused(_run(APP_BASE_URL="http://example.com"), "APP_BASE_URL", "localhost")


def test_refuses_http_base_url_on_lan_address():
    _assert_refused(_run(APP_BASE_URL="http://192.168.1.10:8000"), "APP_BASE_URL")


def test_refuses_base_url_without_scheme():
    _assert_refused(_run(APP_BASE_URL="localhost:8000"), "APP_BASE_URL")


def test_refuses_base_url_with_path():
    _assert_refused(_run(APP_BASE_URL="http://localhost:8000/api"), "APP_BASE_URL")


@pytest.mark.parametrize(
    "url",
    ["http://localhost:8000", "http://127.0.0.1:8000", "http://localhost"],
)
def test_accepts_http_localhost(url: str):
    _assert_accepted(_run(APP_BASE_URL=url))


def test_accepts_https_any_host_and_derives_secure_cookies():
    result = _run(APP_BASE_URL="https://honor.example.com")
    _assert_accepted(result)
    assert "COOKIE_SECURE=True" in result.stdout
    assert "REDIRECT=https://honor.example.com/api/auth/google/callback" in result.stdout


def test_http_localhost_derives_insecure_cookies():
    result = _run(APP_BASE_URL="http://localhost:8000")
    _assert_accepted(result)
    assert "COOKIE_SECURE=False" in result.stdout


def test_surrounding_whitespace_in_base_url_is_tolerated():
    result = _run(APP_BASE_URL="  http://localhost:8000 \n")
    _assert_accepted(result)
    assert "REDIRECT=http://localhost:8000/api/auth/google/callback" in result.stdout


def test_refuses_short_session_secret():
    _assert_refused(_run(SESSION_SECRET="too-short"), "SESSION_SECRET", "32 bytes")


def test_refuses_empty_allowed_emails():
    _assert_refused(_run(ALLOWED_EMAILS=" , "), "ALLOWED_EMAILS")


def test_refuses_missing_google_client_id():
    _assert_refused(_run(GOOGLE_CLIENT_ID=None), "GOOGLE_CLIENT_ID")


def test_removed_variables_are_ignored_not_required():
    # The Railway-era variables must have no effect either way.
    _assert_accepted(
        _run(
            FRONTEND_ORIGINS=None,
            FRONTEND_ORIGINS_PATTERNS=None,
            OAUTH_REDIRECT_URI=None,
        )
    )
