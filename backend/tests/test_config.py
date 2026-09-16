"""Where the engine keeps its state, whatever directory it was started from."""

from __future__ import annotations

from pathlib import Path

from qa_engine import config


def test_the_default_database_does_not_depend_on_the_working_directory():
    """Launched from the repository root instead of `backend/`, a relative default made
    the engine create an empty `qa_engine.db` beside the real one. Every project appeared
    to have vanished, and nothing said why."""
    default = config.Settings.model_fields["database_url"].default
    path = Path(default.removeprefix("sqlite:///"))
    assert path.is_absolute()
    assert path.parent == config.BACKEND_DIR


def test_the_env_file_is_read_from_the_backend_directory():
    assert config.ENV_FILE.is_absolute()
    assert config.ENV_FILE.parent == config.BACKEND_DIR
    assert (config.BACKEND_DIR / "src" / "qa_engine" / "config.py").is_file()
