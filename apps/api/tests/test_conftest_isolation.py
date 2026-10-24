"""The suite must never run against a database exported in the shell.

conftest assigns DATABASE_URL unconditionally. This runs a tiny pytest
session in a subprocess with a foreign DATABASE_URL exported and asserts the
foreign database is untouched afterward.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]


def test_suite_ignores_exported_database_url(tmp_path: Path):
    foreign = tmp_path / "precious.db"
    conn = sqlite3.connect(foreign)
    conn.executescript(
        "CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT);"
        "CREATE TABLE sessions (id TEXT PRIMARY KEY);"
        "INSERT INTO users VALUES ('u1', 'keep@example.com');"
    )
    conn.commit()
    conn.close()

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{foreign}"
    env["APP_BASE_URL"] = "https://should-be-overridden.example.com"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "tests/test_db.py::test_health_reports_connected",
         "tests/test_auth_routes.py::test_callback_creates_user_and_session_and_sets_cookie"],
        cwd=API_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    conn = sqlite3.connect(foreign)
    rows = conn.execute("SELECT email FROM users").fetchall()
    conn.close()
    assert rows == [("keep@example.com",)], "the exported database was touched by the suite"
