from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./qa_engine.db"
    api_v1_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
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
        root = Path(self.work_directory).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root


settings = Settings()
