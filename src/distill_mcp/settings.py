"""Configuration via environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    backend: str = "local"
    data_dir: str = "~/.team-memory"
    ollama_host: str = "http://localhost:11434"
    embedding_model: str = "nomic-embed-text"
    llm_model: str = "gemma3:4b"
    default_author: str = "unknown"
    rrf_k: int = 60
    max_memory_size: int = 8000
    fts_language: str = "simple"
    distill_enabled: bool = True
    distill_preview: bool = (
        True  # When True, remember() returns preview instead of storing
    )


settings = Settings()
