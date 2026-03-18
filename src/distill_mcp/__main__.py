"""Entry point — wires adapters, injects into service, starts MCP server."""

import sys


def _run_server() -> None:
    from pathlib import Path

    from distill_mcp.adapters.distiller.ollama_distill import OllamaDistiller
    from distill_mcp.adapters.scanner.secret_scanner import SecretScanner
    from distill_mcp.domain.services import MemoryService
    from distill_mcp.server import mcp, set_service
    from distill_mcp.settings import settings

    if settings.backend == "gcp":
        import asyncio

        from distill_mcp.adapters.embeddings.vertex_embed import VertexEmbedder
        from distill_mcp.adapters.storage.postgres_store import PostgresStore

        if not settings.gcp_project:
            raise RuntimeError("GCP_PROJECT is required when BACKEND=gcp")

        store = PostgresStore(dsn=settings.database_url)
        asyncio.get_event_loop().run_until_complete(store.initialize())
        embedder = VertexEmbedder(
            project=settings.gcp_project,
            location=settings.gcp_location,
        )
    elif settings.backend == "postgres":
        import asyncio

        from distill_mcp.adapters.embeddings.ollama_embed import OllamaEmbedder
        from distill_mcp.adapters.storage.postgres_store import PostgresStore

        store = PostgresStore(dsn=settings.database_url)
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
    )
    set_service(service)
    mcp.run(transport="stdio")


def _install_skills() -> None:
    """Copy bundled Claude Code skills to ~/.claude/skills/."""
    import shutil
    from importlib.resources import files
    from pathlib import Path

    target_root = Path.home() / ".claude" / "skills"
    source_root = files("distill_mcp") / "skills"

    for skill_dir in source_root.iterdir():
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue

        dest = target_root / skill_dir.name
        if dest.is_symlink():
            dest.unlink()
        if dest.exists():
            shutil.rmtree(dest)

        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(skill_md), str(dest / "SKILL.md"))
        print(f"Installed skill: {skill_dir.name} → {dest}")

    print("Done. Restart Claude Code to pick up new skills.")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "install-skills":
        _install_skills()
        return
    _run_server()


if __name__ == "__main__":
    main()
