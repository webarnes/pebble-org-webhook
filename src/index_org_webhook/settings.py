from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_LLM_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    index_webhook_secret: str = Field(default="", alias="INDEX_WEBHOOK_SECRET")
    index_require_signature: bool = Field(default=True, alias="INDEX_REQUIRE_SIGNATURE")
    index_auth_token: str = Field(default="", alias="INDEX_AUTH_TOKEN")
    timestamp_leeway_seconds: int = Field(default=300, alias="TIMESTAMP_LEEWAY_SECONDS")

    org_directory: Path = Field(default=Path("~/Documents/Org").expanduser(), alias="ORG_DIRECTORY")
    todo_filename: str = Field(default="todo.org", alias="TODO_FILENAME")
    daily_template_path: Path | None = Field(default=None, alias="DAILY_TEMPLATE_PATH")
    timezone: str = Field(default="America/Toronto", alias="ORG_TIMEZONE")
    deliveries_db: Path = Field(default=Path("deliveries.db"), alias="DELIVERIES_DB")

    llm_base_url: str = Field(default=DEFAULT_LLM_BASE_URL, alias="LLM_BASE_URL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default="gemini-2.5-flash", alias="LLM_MODEL")
    llm_timeout_seconds: float = Field(default=15.0, alias="LLM_TIMEOUT_SECONDS")

    bind_host: str = Field(default="127.0.0.1", alias="BIND_HOST")
    bind_port: int = Field(default=8787, alias="BIND_PORT")

    @property
    def llm_configured(self) -> bool:
        base = self.llm_base_url.strip().rstrip("/")
        if not base:
            return False
        return bool(self.llm_api_key.strip()) or base != DEFAULT_LLM_BASE_URL

    @property
    def todo_path(self) -> Path:
        return self.org_directory / self.todo_filename

    @property
    def daily_dir(self) -> Path:
        return self.org_directory / "roam" / "daily"

    @property
    def resolved_daily_template(self) -> Path:
        if self.daily_template_path is not None:
            return self.daily_template_path
        return self.org_directory / "templates" / "roam.dailies.default.txt"


@lru_cache
def get_settings() -> Settings:
    return Settings()
