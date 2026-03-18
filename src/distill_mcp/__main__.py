"""Entry point — wires adapters, injects into service, starts MCP server."""

import sys


def _run_server() -> None:
    from distill_mcp.adapters.distiller.ollama_distill import OllamaDistiller
    from distill_mcp.adapters.embeddings.ollama_embed import OllamaEmbedder
    from distill_mcp.adapters.storage.sqlite_store import SqliteStore
    from distill_mcp.domain.services import MemoryService
    from distill_mcp.server import mcp, set_service
    from distill_mcp.settings import settings

    store = SqliteStore(settings.data_dir, rrf_k=settings.rrf_k)
    store.initialize()

    embedder = OllamaEmbedder(host=settings.ollama_host, model=settings.embedding_model)
    distiller = OllamaDistiller(host=settings.ollama_host, model=settings.llm_model)

    service = MemoryService(
        storage=store,
        embedder=embedder,
        distiller=distiller,
        distill_enabled=settings.distill_enabled,
        distill_preview=settings.distill_preview,
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
