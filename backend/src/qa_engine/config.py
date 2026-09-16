import os
from pathlib import Path

from dotenv import dotenv_values
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# The backend directory, found from this file rather than from wherever the process was
# started. Both defaults below used to be relative to the working directory: launched from
# the repository root instead of `backend/`, the engine silently created an empty
# `qa_engine.db` beside the real one and stopped reading `backend/.env`. Every project
# appeared to have vanished, and nothing said why.
BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    database_url: str = f"sqlite:///{(BACKEND_DIR / 'qa_engine.db').as_posix()}"
    api_v1_prefix: str = "/api/v1"
    # The frontend dev server listens on 8080. The default used to name 5173 and 3000
    # only, so an engine started without a `.env` refused every call from the interface.
    cors_origins: str = "http://localhost:8080,http://127.0.0.1:8080"
    allowed_repository_roots: str = ""

    # Local generation engine. No key, no remote provider: Ollama runs on this machine.
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:4b"
    ollama_timeout_seconds: int = 900
    generation_language: str = "fr"
    # CPU-only inference makes generation the slowest part of an analysis. Bound the
    # number of features generated per run; 0 means every detected feature.
    generation_enabled: bool = True
    generation_max_features: int = 3

    # Jira Cloud, read-only. Credentials stay server-side and are never returned by the
    # API. Create a token at https://id.atlassian.com/manage-profile/security/api-tokens
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    # Jira has no standard acceptance-criteria field; set the custom field id if your
    # team uses one, e.g. "customfield_10041".
    jira_acceptance_criteria_field: str = ""

    # Working directory for cloned repositories and generated artifacts.
    work_directory: str = "work"

    @field_validator("database_url")
    @classmethod
    def _anchor_relative_sqlite(cls, value: str) -> str:
        """Resolve a relative SQLite path against `backend/`, not the working directory.

        `.env.example` long shipped `sqlite:///./qa_engine.db`, and every `.env` copied
        from it keeps that line. Anchoring only the default would leave those installations
        with the very defect the default was fixed for.
        """
        prefix = "sqlite:///"
        if not value.startswith(prefix):
            return value
        path = value[len(prefix) :]
        if not path or path == ":memory:" or Path(path).is_absolute():
            return value
        return f"{prefix}{(BACKEND_DIR / path).resolve().as_posix()}"

    @property
    def allowed_roots(self) -> list[Path]:
        return [
            Path(item).resolve()
            for item in self.allowed_repository_roots.split(",")
            if item.strip()
        ]

    @property
    def clone_root(self) -> Path:
        """Where public git repositories are cloned."""
        root = self.work_root / "clones"
        root.mkdir(parents=True, exist_ok=True)
        return root

    @property
    def work_root(self) -> Path:
        # Anchored like the database, for the same reason: a relative path resolves
        # against wherever the engine happened to be started.
        root = Path(self.work_directory).expanduser()
        if not root.is_absolute():
            root = BACKEND_DIR / root
        root = root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root


settings = Settings()


def export_env_file(path: str | Path = ENV_FILE) -> list[str]:
    """Publish the ``.env`` file into the process environment.

    pydantic-settings reads that file for its own typed fields and stops there — nothing
    lands in ``os.environ``. But a Playwright suite reads its own variables from the
    environment it is launched in (a repository's real-session tests want credentials, for
    instance), and the engine hands the subprocess a copy of ``os.environ``. Without this,
    the only place such a variable could be set was the shell that started the service,
    which is invisible to anyone reading the configuration file.

    An existing variable always wins: what the operator exported for this run is a
    deliberate act, and a file should not silently override it.

    Returns the names published, never their values — these are secrets, and the log of a
    run is persisted and displayed.
    """
    published: list[str] = []
    for key, value in dotenv_values(path).items():
        if value is None or key in os.environ:
            continue
        os.environ[key] = value
        published.append(key)
    return published
