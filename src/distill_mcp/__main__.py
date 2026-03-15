"""Entry point — wires adapters, injects into service, starts MCP server."""

from distill_mcp.adapters.distiller.ollama_distill import OllamaDistiller
from distill_mcp.adapters.embeddings.ollama_embed import OllamaEmbedder
from distill_mcp.adapters.storage.sqlite_store import SqliteStore
from distill_mcp.domain.services import MemoryService
from distill_mcp.server import mcp, set_service
from distill_mcp.settings import settings


def main() -> None:
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


if __name__ == "__main__":
    main()
