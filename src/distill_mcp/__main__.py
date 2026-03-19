"""Entry point — wires adapters, injects into service, starts MCP server."""


def _run_server() -> None:
    from pathlib import Path

    from distill_mcp.adapters.distiller.ollama_distill import OllamaDistiller
    from distill_mcp.adapters.scanner.secret_scanner import SecretScanner
    from distill_mcp.domain.services import MemoryService
    from distill_mcp.server import mcp, set_service
    from distill_mcp.settings import settings

    # Resolve identity when auth is enabled
    identity = None
    if settings.auth_enabled:
        from distill_mcp.adapters.identity.git_identity import resolve_git_identity

        identity = resolve_git_identity()

    if settings.backend == "gcp":
        import asyncio

        from distill_mcp.adapters.embeddings.vertex_embed import VertexEmbedder
        from distill_mcp.adapters.storage.postgres_store import PostgresStore

        if not settings.gcp_project:
            raise RuntimeError("GCP_PROJECT is required when BACKEND=gcp")

        store = PostgresStore(dsn=settings.database_url, identity=identity)
        asyncio.get_event_loop().run_until_complete(store.initialize())
        embedder = VertexEmbedder(
            project=settings.gcp_project,
            location=settings.gcp_location,
        )
    elif settings.backend == "postgres":
        import asyncio

        from distill_mcp.adapters.embeddings.ollama_embed import OllamaEmbedder
        from distill_mcp.adapters.storage.postgres_store import PostgresStore

        store = PostgresStore(dsn=settings.database_url, identity=identity)
        asyncio.get_event_loop().run_until_complete(store.initialize())
        embedder = OllamaEmbedder(
            host=settings.ollama_host, model=settings.embedding_model
        )
    else:
        from distill_mcp.adapters.embeddings.ollama_embed import OllamaEmbedder
        from distill_mcp.adapters.storage.sqlite_store import SqliteStore

        store = SqliteStore(settings.data_dir, rrf_k=settings.rrf_k)
        store.initialize()
        embedder = OllamaEmbedder(
            host=settings.ollama_host, model=settings.embedding_model
        )

    # Distiller stays local Ollama regardless of backend (privacy constraint)
    distiller = OllamaDistiller(host=settings.ollama_host, model=settings.llm_model)

    private_dir = Path(settings.data_dir).expanduser() / "private"

    scanner = SecretScanner()

    reranker = None
    if settings.rerank_enabled and settings.jina_api_key:
        from distill_mcp.adapters.reranker.jina_rerank import JinaReranker

        reranker = JinaReranker(
            api_key=settings.jina_api_key,
            model=settings.rerank_model,
        )

    service = MemoryService(
        storage=store,
        embedder=embedder,
        distiller=distiller,
        distill_enabled=settings.distill_enabled,
        preview_enabled=settings.preview_enabled,
        preview_ttl_seconds=settings.preview_ttl_seconds,
        private_dir=private_dir,
        scanner=scanner,
        max_memory_size=settings.max_memory_size,
        identity=identity,
        reranker=reranker,
    )
    set_service(service)
    mcp.run(transport="stdio")


def _print_seed_workflow() -> None:
    from pathlib import Path

    skill_path = Path(__file__).parent / "skills" / "seed" / "SKILL.md"
    print(skill_path.read_text())


def main() -> None:
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "check-hardware":
            from distill_mcp.hardware import detect_hardware, format_report

            info = detect_hardware()
            print(format_report(info))
            return
        if cmd == "seed":
            _print_seed_workflow()
            return

    _run_server()


if __name__ == "__main__":
    main()
