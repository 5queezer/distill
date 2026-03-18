"""Configuration via environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    backend: str = "local"
    database_url: str | None = (
        None  # e.g. postgresql://user:pass@localhost:5432/distill
    )
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
    log_level: str = "INFO"
    auth_enabled: bool = False  # Enable git-based identity + RLS
    rerank_enabled: bool = False
    jina_api_key: str | None = None
    rerank_model: str = "jina-reranker-v2-base-multilingual"

    # GCP settings (only used when backend=gcp)
    gcp_project: str | None = None
    gcp_location: str = "us-central1"
    cloud_sql_connection: str | None = None


settings = Settings()
