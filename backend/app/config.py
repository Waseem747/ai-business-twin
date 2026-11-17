"""Application configuration.

Secrets are loaded from environment variables (or .env).  Nothing sensitive is
persisted in the repository.  The default local profile is deliberately
self-contained (SQLite, deterministic narrative provider) so the MVP can be
demonstrated without external credentials.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Business Twin"
    app_env: str = "development"
    app_version: str = "0.1.0"
    app_base_url: str = "http://localhost:8000"
    frontend_origins: str = "http://localhost:5173,http://localhost:4173"
    demo_mode: bool = True
    demo_auto_bootstrap: bool = True

    database_url: str = f"sqlite+aiosqlite:///{(BACKEND_DIR / 'data' / 'runtime' / 'business_twin.db').as_posix()}"
    checkpoint_db: str = str(BACKEND_DIR / "data" / "runtime" / "checkpoints.sqlite")
    storage_dir: str = str(BACKEND_DIR / "storage")

    jwt_secret: str = "dev-only-change-me-please-32-chars-minimum"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 480
    cookie_secure: bool = False
    credential_encryption_key: str = ""

    llm_provider: str = "deterministic"  # deterministic | openai | ollama
    llm_model: str = "gpt-4.1-mini"
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

    scheduler_enabled: bool = True
    daily_report_cron_hour: int = 7
    daily_report_cron_minute: int = 0
    timezone: str = "UTC"

    human_approval_threshold_usd: float = 5000.0
    max_audit_rounds: int = 2
    sandbox_timeout_seconds: int = 8
    data_stale_after_hours: int = 48
    rate_limit_per_minute: int = 240

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    notification_email_to: str = ""

    pos_api_base_url: str = ""
    pos_api_token: str = ""
    erp_api_base_url: str = ""
    erp_api_token: str = ""

    @field_validator("llm_provider")
    @classmethod
    def _valid_provider(cls, value: str) -> str:
        if value not in {"deterministic", "openai", "ollama"}:
            raise ValueError("LLM_PROVIDER must be deterministic, openai or ollama")
        return value

    @field_validator("database_url")
    @classmethod
    def _absolute_sqlite_path(cls, value: str) -> str:
        if value.startswith("sqlite") and ":///" in value:
            prefix, raw = value.split(":///", 1)
            path = Path(raw)
            if not path.is_absolute():
                path = (BACKEND_DIR / raw.replace("./", "")).resolve()
            return f"{prefix}:///{path.as_posix()}"
        return value

    @field_validator("checkpoint_db", "storage_dir")
    @classmethod
    def _absolute_path(cls, value: str) -> str:
        path = Path(value)
        if not path.is_absolute():
            path = (BACKEND_DIR / value.replace("./", "")).resolve()
        return str(path)

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_dir).resolve()

    @property
    def runtime_path(self) -> Path:
        return BACKEND_DIR / "data" / "runtime"

    def ensure_directories(self) -> None:
        for path in (
            self.storage_path,
            self.storage_path / "reports",
            self.storage_path / "uploads",
            self.storage_path / "exports",
            self.runtime_path,
        ):
            path.mkdir(parents=True, exist_ok=True)
        if self.is_sqlite:
            db_path = self.database_url.split("///", 1)[-1]
            Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings


settings = get_settings()

# LangSmith is configured through environment variables understood by LangChain.
if os.getenv("LANGSMITH_TRACING", "").lower() == "true":
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    if os.getenv("LANGSMITH_API_KEY"):
        os.environ.setdefault("LANGCHAIN_API_KEY", os.environ["LANGSMITH_API_KEY"])
    os.environ.setdefault("LANGCHAIN_PROJECT", os.getenv("LANGSMITH_PROJECT", "business-twin"))
