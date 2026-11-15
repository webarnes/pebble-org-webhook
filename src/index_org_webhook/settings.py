from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    bind_host: str = Field(default="127.0.0.1", alias="BIND_HOST")
    bind_port: int = Field(default=8787, alias="BIND_PORT")

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
