from functools import lru_cache
from typing import Annotated

from pydantic import Field, PostgresDsn, UrlConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict

PsycopgDsn = Annotated[PostgresDsn, UrlConstraints(allowed_schemes=["postgresql+psycopg"])]


class Settings(BaseSettings):
    """Validated process environment. Fails fast on startup when misconfigured."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: PsycopgDsn = Field(description="SQLAlchemy URL, postgresql+psycopg://...")


@lru_cache
def get_settings() -> Settings:
    return Settings()
