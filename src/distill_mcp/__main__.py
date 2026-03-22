"""Entry point — wires adapters, injects into service, starts MCP server."""

from __future__ import annotations


def _init_store() -> tuple:
    """Initialize storage adapter based on backend config.

    Returns (store, needs_async_init, identity).
    Caller must handle async init if needed.
    """
    from distill_mcp.settings import settings

    identity = None
    if settings.auth_enabled:
        from distill_mcp.adapters.identity.git_identity import resolve_git_identity

        identity = resolve_git_identity()

    if settings.backend == "postgres":
        from distill_mcp.adapters.storage.postgres_store import PostgresStore

        store = PostgresStore(dsn=settings.database_url, identity=identity)
        return store, True, identity
    else:
        from distill_mcp.adapters.storage.sqlite_store import SqliteStore

        store = SqliteStore(settings.data_dir, rrf_k=settings.rrf_k)
        return store, False, identity


def _run_server() -> None:
    import asyncio
    from pathlib import Path

    import structlog
    from aiohttp import web

    from distill_mcp.adapters.scanner.secret_scanner import SecretScanner
    from distill_mcp.domain.services import MemoryService
    from distill_mcp.ingest import create_ingest_app
    from distill_mcp.server import mcp, set_service
    from distill_mcp.settings import settings
    from distill_mcp.worker import ObservationWorker

    logger = structlog.get_logger()

    store, needs_async_init, identity = _init_store()
    if needs_async_init:
        asyncio.get_event_loop().run_until_complete(store.initialize())
    else:
        store.initialize()

    # Provider defaults — used when EMBEDDING_MODEL / LLM_MODEL not set
    _embedding_defaults = {
        "ollama": "nomic-embed-text",
        "gemini": "gemini-embedding-001",
        "vertex": "text-embedding-005",
        "bedrock": "amazon.titan-embed-text-v2:0",
        "azure": "text-embedding-3-small",
    }
    _llm_defaults = {
        "ollama": "gemma3:4b",
        "gemini": "gemini-2.0-flash",
    }

    ep = settings.embedding_provider
    dp = settings.distiller_provider
    embedding_model = settings.embedding_model or _embedding_defaults.get(
        ep, "nomic-embed-text"
    )
    llm_model = settings.llm_model or _llm_defaults.get(dp, "gemma3:4b")

    # Embedding provider
    if ep == "gemini":
        from distill_mcp.adapters.embeddings.gemini_embed import GeminiEmbedder

        if not settings.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is required when EMBEDDING_PROVIDER=gemini"
            )
        embedder = GeminiEmbedder(
            api_key=settings.gemini_api_key,
            model=embedding_model,
        )
    elif ep == "vertex":
        from distill_mcp.adapters.embeddings.vertex_embed import VertexEmbedder

        if not settings.gcp_project:
            raise RuntimeError("GCP_PROJECT is required when EMBEDDING_PROVIDER=vertex")
        embedder = VertexEmbedder(
            project=settings.gcp_project,
            location=settings.gcp_location,
        )
    elif ep == "bedrock":
        from distill_mcp.adapters.embeddings.bedrock_embed import BedrockEmbedder

        embedder = BedrockEmbedder(
            region=settings.aws_region,
            model=embedding_model,
        )
    elif ep == "azure":
        from distill_mcp.adapters.embeddings.azure_embed import AzureOpenAIEmbedder

        if not settings.azure_openai_endpoint or not settings.azure_openai_api_key:
            raise RuntimeError(
                "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY are required "
                "when EMBEDDING_PROVIDER=azure"
            )
        embedder = AzureOpenAIEmbedder(
            endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            deployment=embedding_model,
        )
    else:
        from distill_mcp.adapters.embeddings.ollama_embed import OllamaEmbedder

        embedder = OllamaEmbedder(host=settings.ollama_host, model=embedding_model)

    # Distillation provider
    if dp == "gemini":
        from distill_mcp.adapters.distiller.gemini_distill import GeminiDistiller

        if not settings.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is required when DISTILLER_PROVIDER=gemini"
            )
        distiller = GeminiDistiller(
            api_key=settings.gemini_api_key,
            model=llm_model,
        )
    else:
        from distill_mcp.adapters.distiller.ollama_distill import OllamaDistiller

        distiller = OllamaDistiller(host=settings.ollama_host, model=llm_model)

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
        scanner=scanner,
        max_memory_size=settings.max_memory_size,
        identity=identity,
        reranker=reranker,
    )
    set_service(service)

    observe_dir = Path(settings.data_dir).expanduser() / "private"
    observe_jsonl = observe_dir / "observations.jsonl"
    observe_cursor = observe_dir / ".cursor"
    wake_event = asyncio.Event()

    worker = ObservationWorker(
        jsonl_path=observe_jsonl,
        cursor_path=observe_cursor,
        wake_event=wake_event,
        distiller=distiller,
        embedder=embedder,
        storage=store,
        scanner=scanner,
        distill_enabled=settings.distill_enabled,
        max_memory_size=settings.max_memory_size,
    )

    ingest_app = create_ingest_app(observe_jsonl, wake_event)

    async def _validate_embedding_dim() -> None:
        """Check that current embedding model matches stored vector dimensions."""
        if not hasattr(store, "get_vector_dimension"):
            return
        stored_dim = store.get_vector_dimension()
        if stored_dim is None:
            return
        try:
            test_vec = await embedder.embed("dimension check")
        except RuntimeError:
            logger.warning("embedding_dim_check_skipped", reason="embedder unreachable")
            return
        current_dim = len(test_vec)
        if current_dim != stored_dim:
            # Try to get stored model name for a better error message
            stored_model = None
            if hasattr(store, "get_embedding_meta"):
                meta = store.get_embedding_meta()
                if asyncio.iscoroutine(meta):
                    stored_model, _ = await meta
                else:
                    stored_model, _ = meta
            raise RuntimeError(
                f"Embedding dimension mismatch: stored vectors have {stored_dim} "
                f"dimensions (model: {stored_model or 'unknown'}) but current model "
                f"'{embedding_model}' produces {current_dim} dimensions. "
                f"Delete the vector store and restart to re-embed all memories, "
                f"or switch back to the original embedding model."
            )
        if hasattr(store, "save_embedding_meta"):
            result = store.save_embedding_meta(embedding_model, current_dim)
            if asyncio.iscoroutine(result):
                await result
        logger.info(
            "embedding_dim_validated",
            model=embedding_model,
            dim=current_dim,
        )

    async def _run_all() -> None:
        """Start ingest HTTP server + worker, then run MCP stdio server."""
        observe_dir.mkdir(parents=True, exist_ok=True)
        await _validate_embedding_dim()
        runner = web.AppRunner(ingest_app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", settings.ingest_port)
        await site.start()
        logger.info("ingest_server_started", port=settings.ingest_port)
        worker_task = asyncio.create_task(worker.run_forever())
        await mcp.run_stdio_async()
        worker_task.cancel()

    asyncio.run(_run_all())


def _export_memories(
    fmt: str,
    output: str | None,
    repo: str | None,
    type_filter: str | None,
    after: str | None,
) -> None:
    import asyncio
    import csv
    import io
    import json
    import sys
    from dataclasses import asdict
    from datetime import datetime

    store, needs_async_init, _identity = _init_store()
    if needs_async_init:
        asyncio.get_event_loop().run_until_complete(store.initialize())
    else:
        store.initialize()

    memories = asyncio.get_event_loop().run_until_complete(
        store.list_recent(repo=repo, type=type_filter, limit=10000)
    )

    if after:
        cutoff = datetime.fromisoformat(after)
        memories = [m for m in memories if m.created_at >= cutoff]

    fields = [
        "id",
        "content",
        "type",
        "repos",
        "tags",
        "author",
        "created_at",
        "access_count",
        "last_accessed_at",
        "agent_id",
    ]

    def _serialize(obj: object) -> str:
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Not serializable: {type(obj)}")

    rows = []
    for m in memories:
        d = asdict(m)
        rows.append({k: d[k] for k in fields})

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            row["repos"] = ";".join(row["repos"])
            row["tags"] = ";".join(row["tags"])
            if row["created_at"]:
                row["created_at"] = row["created_at"].isoformat()
            if row["last_accessed_at"]:
                row["last_accessed_at"] = row["last_accessed_at"].isoformat()
            writer.writerow(row)
        text = buf.getvalue()
    else:
        text = json.dumps(rows, default=_serialize, indent=2)

    if output:
        with open(output, "w") as f:
            f.write(text)
        print(f"Exported {len(rows)} memories to {output}", file=sys.stderr)
    else:
        print(text)


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
        if cmd == "export":
            args = sys.argv[2:]
            fmt = "json"
            output = None
            repo = None
            type_filter = None
            after = None
            i = 0
            while i < len(args):
                if args[i] == "--format" and i + 1 < len(args):
                    fmt = args[i + 1]
                    i += 2
                elif args[i] == "--output" and i + 1 < len(args):
                    output = args[i + 1]
                    i += 2
                elif args[i] == "--repo" and i + 1 < len(args):
                    repo = args[i + 1]
                    i += 2
                elif args[i] == "--type" and i + 1 < len(args):
                    type_filter = args[i + 1]
                    i += 2
                elif args[i] == "--after" and i + 1 < len(args):
                    after = args[i + 1]
                    i += 2
                else:
                    print(f"Unknown argument: {args[i]}", file=sys.stderr)
                    sys.exit(1)
            if fmt not in ("json", "csv"):
                print(f"Unsupported format: {fmt}", file=sys.stderr)
                sys.exit(1)
            _export_memories(fmt, output, repo, type_filter, after)
            return

    _run_server()


if __name__ == "__main__":
    main()
