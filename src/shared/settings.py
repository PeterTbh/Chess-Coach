"""Application settings loaded from .env via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    lichess_username: str = ""
    chesscom_username: str = ""
    api_url: str = "http://localhost:8000"
    stockfish_path: str = "stockfish"
    chroma_persist_dir: str = "data/chroma"
    embedder_model: str = "BAAI/bge-small-en-v1.5"
    corpus_seed_path: str = "data/corpus_seed.json"
    corpus_collection: str = "caissa_corpus_v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout_seconds: float = 30.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
