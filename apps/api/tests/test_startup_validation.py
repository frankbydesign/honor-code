"""Confirm that the app refuses to boot if FRONTEND_ORIGINS_PATTERNS
contains an unsafe pattern. We can't reload `app.auth.config` cleanly
within a single test process (other modules cache references to its
constants), so each negative case runs in a fresh subprocess.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest


def _run_with_pattern(pattern: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["FRONTEND_ORIGINS_PATTERNS"] = pattern
    code = textwrap.dedent(
        """
        import sys
        try:
            import app.auth.config  # noqa: F401
        except RuntimeError as exc:
            sys.stderr.write(str(exc))
            sys.exit(2)
        sys.exit(0)
        """
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "bad",
    [
        "*",
        "*.vercel.app",
        "https://*",
        "https://honor-code-*",
    ],
)
def test_startup_refuses_open_ended_pattern(bad: str):
    result = _run_with_pattern(bad)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "leading or trailing wildcard" in result.stderr
    assert repr(bad) in result.stderr


def test_startup_refuses_pattern_without_scheme():
    result = _run_with_pattern("honor-code-*-cpdigital.vercel.app")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "must include a scheme" in result.stderr


def test_startup_accepts_empty_pattern_env():
    result = _run_with_pattern("")
    assert result.returncode == 0, result.stdout + result.stderr


def test_startup_accepts_well_formed_pattern():
    result = _run_with_pattern("https://honor-code-*-cpdigital.vercel.app")
    assert result.returncode == 0, result.stdout + result.stderr
