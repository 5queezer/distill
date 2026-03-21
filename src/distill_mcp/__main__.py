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

    from distill_mcp.adapters.scanner.secret_scanner import SecretScanner
    from distill_mcp.domain.services import MemoryService
    from distill_mcp.server import mcp, set_service
    from distill_mcp.settings import settings

    store, needs_async_init, identity = _init_store()
    if needs_async_init:
        asyncio.get_event_loop().run_until_complete(store.initialize())
    else:
        store.initialize()

    # Provider defaults — used when EMBEDDING_MODEL / LLM_MODEL not set
    _embedding_defaults = {
        "ollama": "nomic-embed-text",
        "gemini": "text-embedding-004",
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
