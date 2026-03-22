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


def _init_embedder() -> tuple:
    """Initialize embedding adapter based on config.

    Returns (embedder, embedding_model_name).
    """
    from distill_mcp.settings import settings

    # Provider defaults — used when EMBEDDING_MODEL not set
    _embedding_defaults = {
        "ollama": "nomic-embed-text",
        "gemini": "gemini-embedding-001",
        "vertex": "text-embedding-005",
        "bedrock": "amazon.titan-embed-text-v2:0",
        "azure": "text-embedding-3-small",
    }

    ep = settings.embedding_provider
    embedding_model = settings.embedding_model or _embedding_defaults.get(
        ep, "nomic-embed-text"
    )

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

    return embedder, embedding_model


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

    _llm_defaults = {
        "ollama": "gemma3:4b",
        "gemini": "gemini-2.0-flash",
    }

    dp = settings.distiller_provider
    llm_model = settings.llm_model or _llm_defaults.get(dp, "gemma3:4b")

    embedder, embedding_model = _init_embedder()

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
        stored_dim = store.get_vector_dimension()
        if stored_dim is None:
            return
        stored_model, _ = await store.get_embedding_meta()
        if stored_model == embedding_model:
            logger.info(
                "embedding_dim_validated", model=embedding_model, dim=stored_dim
            )
            return
        try:
            test_vec = await embedder.embed("dimension check")
        except RuntimeError:
            logger.warning("embedding_dim_check_skipped", reason="embedder unreachable")
            return
        current_dim = len(test_vec)
        if current_dim != stored_dim:
            raise RuntimeError(
                f"Embedding dimension mismatch: stored vectors have {stored_dim} "
                f"dimensions (model: {stored_model or 'unknown'}) but current model "
                f"'{embedding_model}' produces {current_dim} dimensions. "
                f"Run 'uv run python -m distill_mcp reembed' to rebuild vectors, "
                f"or switch back to the original embedding model."
            )
        await store.save_embedding_meta(embedding_model, current_dim)
        logger.info("embedding_dim_validated", model=embedding_model, dim=current_dim)

    async def _purge_expired_memories() -> None:
        """Hard-delete soft-deleted memories past the retention period."""
        if settings.retention_days > 0:
            purged = await service.purge_expired(settings.retention_days)
            if purged:
                logger.info(
                    "retention_purge_complete",
                    purged=purged,
                    retention_days=settings.retention_days,
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
        purge_task = asyncio.create_task(_purge_expired_memories())
        await mcp.run_stdio_async()
        purge_task.cancel()
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


async def _reembed_async(store, embedder, embedding_model: str, data_dir: str) -> int:
    """Re-embed all memories. Returns count of re-embedded memories."""
    import shutil
    import sys
    from pathlib import Path

    memories = await store.list_recent(limit=100000)
    if not memories:
        print("No memories to re-embed.", file=sys.stderr)
        return 0

    # Back up existing lance dir
    lance_dir = Path(data_dir).expanduser() / "lance"
    if lance_dir.exists():
        old_dim = store.get_vector_dimension() or "unknown"
        backup = lance_dir.with_name(f"lance.bak.{old_dim}")
        if backup.exists():
            shutil.rmtree(backup)
        shutil.copytree(lance_dir, backup)
        print(f"Backed up lance/ → {backup.name}/", file=sys.stderr)

    # Drop old vectors table
    if hasattr(store, "_lance") and store._lance is not None:
        if "vectors" in store._lance.list_tables().tables:
            store._lance.drop_table("vectors")
        store._stored_vec_dim = None

    count = 0
    for mem in memories:
        vec = await embedder.embed(mem.content)
        data = [{"id": mem.id, "vector": vec, "agent_id": mem.agent_id or ""}]
        if "vectors" in store._lance.list_tables().tables:
            store._lance.open_table("vectors").add(data)
        else:
            store._lance.create_table("vectors", data)
            store._stored_vec_dim = len(vec)
        count += 1
        print(
            f"\r  Re-embedding {count}/{len(memories)}...",
            end="",
            file=sys.stderr,
        )
    new_dim = store._stored_vec_dim or len(await embedder.embed("dim"))
    await store.save_embedding_meta(embedding_model, new_dim)
    print(
        f"\nDone. Re-embedded {count} memories with {embedding_model}.",
        file=sys.stderr,
    )
    return count


def _reembed() -> None:
    """CLI entry point for re-embedding."""
    import asyncio

    from distill_mcp.settings import settings

    store, needs_async_init, _identity = _init_store()
    if needs_async_init:
        asyncio.run(store.initialize())
    else:
        store.initialize()

    embedder, embedding_model = _init_embedder()
    asyncio.run(_reembed_async(store, embedder, embedding_model, settings.data_dir))


def _run_seed(since: str | None = None, port: int | None = None) -> None:
    """Seed the knowledge base from git history.

    Reads git log, filters trivial commits, and POSTs each to the
    ingest endpoint for distillation by the background worker.
    Requires the distill MCP server to be running.
    """
    import json
    import re
    import subprocess
    import sys
    import urllib.error
    import urllib.request

    from distill_mcp.settings import settings

    ingest_port = port or settings.ingest_port
    base_url = f"http://127.0.0.1:{ingest_port}/observe"

    # Must be in a git repo — derive name from remote origin (worktree-safe)
    try:
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: not inside a git repository.", file=sys.stderr)
        sys.exit(1)

    try:
        origin_url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        repo_name = origin_url.rsplit("/", 1)[-1].removesuffix(".git")
    except (subprocess.CalledProcessError, FileNotFoundError):
        # No remote — fall back to toplevel directory name
        toplevel = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        repo_name = toplevel.rsplit("/", 1)[-1]

    # Build git log command
    git_cmd = ["git", "log", "--reverse", "--format=%H%x00%aI%x00%s"]
    if since:
        git_cmd.append(f"--since={since}")

    try:
        log_output = subprocess.check_output(git_cmd, text=True).strip()
    except subprocess.CalledProcessError as exc:
        print(f"Error reading git log: {exc}", file=sys.stderr)
        sys.exit(1)

    if not log_output:
        print("No commits found.", file=sys.stderr)
        return

    commits = log_output.splitlines()

    # Filter patterns for trivial commits
    skip_re = re.compile(
        r"^(chore|style|ci)(\(.+\))?:\s|^Merge\s|^fixup!|^squash!",
        re.IGNORECASE,
    )

    posted = 0
    skipped = 0
    errors = 0

    for line in commits:
        parts = line.split("\x00", 2)
        if len(parts) != 3:
            continue
        sha, date, subject = parts

        if skip_re.match(subject):
            skipped += 1
            continue

        # For short subjects, include the diffstat for context
        body = f"[{date}] {subject}"
        if len(subject) < 72:
            try:
                stat = subprocess.check_output(
                    ["git", "show", "--stat", "--format=", sha],
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
                if stat:
                    body += f"\n\nFiles changed:\n{stat}"
            except subprocess.CalledProcessError:
                pass

        payload = json.dumps(
            {
                "tool_name": "seed",
                "input": f"{repo_name}@{sha[:10]}",
                "output": body,
            }
        ).encode()

        req = urllib.request.Request(
            base_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 202:
                    posted += 1
                else:
                    errors += 1
                    print(
                        f"  Unexpected status {resp.status} for {sha[:10]}",
                        file=sys.stderr,
                    )
        except urllib.error.URLError as exc:
            errors += 1
            if posted == 0 and errors == 1:
                print(
                    f"Error: cannot reach ingest endpoint at {base_url}\n"
                    "Is the distill MCP server running?",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"  Failed to post {sha[:10]}: {exc}", file=sys.stderr)

        if posted % 10 == 0 and posted > 0:
            print(f"  … {posted} commits posted", file=sys.stderr)

    print(
        f"Seed complete: {posted} posted, {skipped} skipped, {errors} errors "
        f"(from {len(commits)} commits in {repo_name})",
        file=sys.stderr,
    )


def main() -> None:
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "check-hardware":
            from distill_mcp.hardware import detect_hardware, format_report

            info = detect_hardware()
            print(format_report(info))
            return
        if cmd == "reembed":
            _reembed()
            return
        if cmd == "seed":
            seed_args = sys.argv[2:]
            since = None
            seed_port = None
            i = 0
            while i < len(seed_args):
                if seed_args[i] == "--since" and i + 1 < len(seed_args):
                    since = seed_args[i + 1]
                    i += 2
                elif seed_args[i] == "--port" and i + 1 < len(seed_args):
                    seed_port = int(seed_args[i + 1])
                    i += 2
                else:
                    print(f"Unknown argument: {seed_args[i]}", file=sys.stderr)
                    sys.exit(1)
            _run_seed(since=since, port=seed_port)
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
        print(
            f"Unknown command: {cmd}\n"
            "Usage: distill [check-hardware|reembed|seed|export]",
            file=sys.stderr,
        )
        sys.exit(1)

    _run_server()


if __name__ == "__main__":
    main()
