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


def test_a_relative_sqlite_path_from_an_old_env_file_is_anchored_too():
    """`.env.example` long shipped `sqlite:///./qa_engine.db`, and every `.env` copied from
    it keeps that line."""
    settings = config.Settings(database_url="sqlite:///./qa_engine.db")
    path = Path(settings.database_url.removeprefix("sqlite:///"))
    assert path.is_absolute()
    assert path == (config.BACKEND_DIR / "qa_engine.db").resolve()


def test_an_absolute_or_non_sqlite_url_is_left_alone():
    absolute = f"sqlite:///{(config.BACKEND_DIR / 'x.db').as_posix()}"
    assert config.Settings(database_url=absolute).database_url == absolute
    postgres = "postgresql://qa@localhost/qa"
    assert config.Settings(database_url=postgres).database_url == postgres


def test_the_interface_origin_is_allowed_without_any_env_file():
    """The frontend dev server listens on 8080; the default named 5173 and 3000 only, so
    an engine started without a `.env` refused every call from the interface."""
    default = config.Settings.model_fields["cors_origins"].default
    assert "http://localhost:8080" in default.split(",")
