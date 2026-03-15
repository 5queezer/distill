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
    preview_enabled: bool = True
    preview_ttl_seconds: int = 300


settings = Settings()
