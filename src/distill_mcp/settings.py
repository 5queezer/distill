"""Configuration via environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Storage backend
    backend: str = "local"  # local | postgres
    database_url: str | None = (
        None  # e.g. postgresql://user:pass@localhost:5432/distill
    )
    data_dir: str = "~/.team-memory"

    # Embedding provider
    embedding_provider: str = "ollama"  # ollama | gemini | vertex | bedrock | azure
    embedding_model: str | None = None  # default per provider (see __main__.py)

    # Distillation provider
    distiller_provider: str = "ollama"  # ollama | gemini
    llm_model: str | None = None  # default per provider (see __main__.py)

    # Ollama (used when embedding_provider=ollama or distiller_provider=ollama)
    ollama_host: str = "http://localhost:11434"

    # Gemini (used when embedding_provider=gemini or distiller_provider=gemini)
    gemini_api_key: str | None = None

    # Vertex AI (used when embedding_provider=vertex)
    gcp_project: str | None = None
    gcp_location: str = "us-central1"
    cloud_sql_connection: str | None = None

    # Bedrock (used when embedding_provider=bedrock)
    aws_region: str = "us-east-1"

    # Azure OpenAI (used when embedding_provider=azure)
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None

    # General
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


settings = Settings()
