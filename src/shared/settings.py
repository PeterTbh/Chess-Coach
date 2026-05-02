"""Application settings loaded from .env via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    lichess_username: str = ""
    chesscom_username: str = ""
    api_url: str = "http://localhost:8000"
    chroma_host: str = "localhost"
    chroma_port: int = 8001

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
