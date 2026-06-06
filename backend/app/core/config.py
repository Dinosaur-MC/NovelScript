"""Application configuration loaded from environment variables.

Uses pydantic-settings BaseSettings for automatic .env loading,
validation, and type coercion.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """NovelScript backend settings.

    All values are read from environment variables or a ``.env`` file
    placed next to ``backend/main.py``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # -- PostgreSQL -----------------------------------------------------------
    DATABASE_URL: str = (
        "postgresql://novelscript:novelscript@localhost:5432/novelscript"
    )

    # -- LLM / AI -------------------------------------------------------------
    DEEPSEEK_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_EMBEDDING_MODEL: str = "openai/text-embedding-3-small"

    # -- Redis / Celery --------------------------------------------------------
    REDIS_URL: str = "redis://localhost:6379/0"

    # -- Application ----------------------------------------------------------
    DEBUG: bool = False

    # -- Initial admin account -------------------------------------------------
    ADMIN_EMAIL: str = "admin@novelscript.local"
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"
    ADMIN_DISPLAY_NAME: str = "Administrator"


# Singleton — import this everywhere
settings = Settings()
