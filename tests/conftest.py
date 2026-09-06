"""Shared pytest configuration.

Some modules (e.g. ``src.database.session``) build the DB engine and read
application settings at *import* time. Pytest imports ``conftest.py`` before
collecting any test module in this directory, so setting sane defaults here
guarantees they are in place before ``src`` is imported for the first time.

Real deployments must still provide these via the environment/``.env`` file;
we only fill in gaps so the test suite doesn't need secrets or a live
Postgres instance.
"""

import os
import tempfile
from pathlib import Path

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-telegram-bot-token")

_TEST_DB_PATH = Path(tempfile.gettempdir()) / "gym_bot_test.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TEST_DB_PATH}")
