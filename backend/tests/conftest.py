"""Test bootstrap.

``qa_engine.config`` builds its Settings singleton at import time, so the test database
must be selected before any ``qa_engine`` module is imported — hence the module-level
environment setup rather than a fixture.
"""

import atexit
import os
import tempfile
from pathlib import Path

# One database per process: deleting a shared file fails on Windows as soon as another
# run still holds a handle on it.
_TEST_DB = Path(tempfile.gettempdir()) / f"qa_engine_tests_{os.getpid()}.db"
if _TEST_DB.exists():
    _TEST_DB.unlink()


def _cleanup() -> None:
    # SQLAlchemy may still hold the connection at interpreter shutdown; a leftover file in
    # the temp directory is harmless, a noisy traceback is not.
    try:
        _TEST_DB.unlink(missing_ok=True)
    except OSError:
        pass


atexit.register(_cleanup)

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"
os.environ.setdefault("CORS_ORIGINS", "http://localhost:8080")
os.environ.setdefault("ALLOWED_REPOSITORY_ROOTS", "")

# The suite must never reach the local model: generation is slow, non-deterministic,
# and unavailable in CI. Generation itself is covered by dedicated unit tests that
# stub the Ollama client.
os.environ["GENERATION_ENABLED"] = "false"
