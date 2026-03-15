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


def _export(args: list[str]) -> None:
    """Export memories: distill export --format timeline [--output FILE] [--repos a,b]."""
    import argparse
    import asyncio
    from pathlib import Path

    from distill_mcp.adapters.storage.sqlite_store import SqliteStore
    from distill_mcp.settings import settings

    parser = argparse.ArgumentParser(prog="distill export")
    parser.add_argument(
        "--format", required=True, choices=["timeline"], help="Export format"
    )
    parser.add_argument(
        "--output",
        "-o",
        default="knowledge-timeline.html",
        help="Output file path (default: knowledge-timeline.html)",
    )
    parser.add_argument("--repos", help="Comma-separated repo filter")
    parser.add_argument("--after", help="Include memories after this date (YYYY-MM)")
    parser.add_argument("--before", help="Include memories before this date (YYYY-MM)")
    opts = parser.parse_args(args)

    store = SqliteStore(settings.data_dir, rrf_k=settings.rrf_k)
    store.initialize()

    repos = (
        [r.strip() for r in opts.repos.split(",") if r.strip()] if opts.repos else None
    )
    memories = asyncio.run(
        store.export_all(repos=repos, after=opts.after, before=opts.before)
    )

    if opts.format == "timeline":
        from distill_mcp.formats.timeline import generate_timeline_html

        html = generate_timeline_html(memories)

    out = Path(opts.output)
    out.write_text(html)
    print(f"Exported {len(memories)} memories → {out}")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "install-skills":
        _install_skills()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "export":
        _export(sys.argv[2:])
        return
    _run_server()


if __name__ == "__main__":
    main()
