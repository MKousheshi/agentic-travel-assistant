from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: SecretStr
    db_path: str
    openai_base_url: str
    langsmith_api_key: SecretStr | None = None
    max_planning_retries: int = 3
    openai_model: str = "gpt-4o-mini"
    log_level: str = "INFO"
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]
