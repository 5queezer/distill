"""Retrieval quality benchmark — measures recall@k for realistic queries.

Covers issue #71: no tests currently measure whether the *right* memories
are returned. This benchmark creates a dataset, embeds it with Ollama,
and tests recall@5 and recall@10 for representative queries.

Requires a running Ollama instance (marked @pytest.mark.ollama).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from distill_mcp.adapters.embeddings.ollama_embed import OllamaEmbedder
from distill_mcp.adapters.storage.sqlite_store import SqliteStore
from distill_mcp.domain.models import Memory
from distill_mcp.domain.services import MemoryService

_MODEL = os.environ.get("DISTILL_TEST_EMBED_MODEL", "nomic-embed-text")


def _ollama_available() -> bool:
    try:
        resp = httpx.get("http://localhost:11434/api/version", timeout=2.0)
        return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.ollama,
    pytest.mark.skipif(not _ollama_available(), reason="Ollama not running"),
]


# -- Sample knowledge base --
# Each entry: (id, content, type, tags)
MEMORIES = [
    (
        "m01",
        "PostgreSQL chosen as primary database for pgvector support and JSONB.",
        "decision",
        ["database", "postgresql"],
    ),
    (
        "m02",
        "Redis used for session caching with 15-minute TTL.",
        "decision",
        ["cache", "redis"],
    ),
    (
        "m03",
        "FastAPI selected for REST API layer due to async support and auto-docs.",
        "decision",
        ["api", "fastapi"],
    ),
    (
        "m04",
        "React with TypeScript for frontend, using Vite as build tool.",
        "decision",
        ["frontend", "react"],
    ),
    (
        "m05",
        "Docker Compose for local development, Kubernetes for production.",
        "decision",
        ["deployment", "docker"],
    ),
    (
        "m06",
        "JWT tokens for API authentication with 1-hour expiry.",
        "decision",
        ["auth", "jwt"],
    ),
    (
        "m07",
        "Alembic for database migrations with auto-generate from SQLAlchemy models.",
        "dependency",
        ["database", "migrations"],
    ),
    (
        "m08",
        "GitHub Actions CI pipeline runs tests, lint, and type-check on every PR.",
        "pattern",
        ["ci", "github-actions"],
    ),
    (
        "m09",
        "Structured logging with structlog, JSON format in production.",
        "pattern",
        ["logging", "observability"],
    ),
    (
        "m10",
        "Feature flags managed via LaunchDarkly for gradual rollouts.",
        "pattern",
        ["feature-flags"],
    ),
    (
        "m11",
        "Rate limiting at 100 requests per minute per API key using Redis.",
        "decision",
        ["rate-limiting", "redis"],
    ),
    (
        "m12",
        "S3 for file storage with pre-signed URLs for client uploads.",
        "decision",
        ["storage", "aws"],
    ),
    (
        "m13",
        "Connection pool failure at 2025-03 caused by leaked connections in async context.",
        "failure",
        ["database", "connection-pool"],
    ),
    (
        "m14",
        "Memory leak in worker process traced to unclosed HTTP sessions.",
        "failure",
        ["memory-leak", "worker"],
    ),
    (
        "m15",
        "Datadog for APM and metrics, PagerDuty for alerting.",
        "dependency",
        ["monitoring", "datadog"],
    ),
    (
        "m16",
        "GraphQL abandoned in favor of REST due to N+1 query complexity.",
        "decision",
        ["api", "graphql"],
    ),
    (
        "m17",
        "Celery with Redis broker for background job processing.",
        "decision",
        ["queue", "celery"],
    ),
    (
        "m18",
        "Python 3.12 minimum version, using match statements.",
        "dependency",
        ["python", "version"],
    ),
    (
        "m19",
        "Test coverage must stay above 80%, enforced in CI.",
        "pattern",
        ["testing", "coverage"],
    ),
    (
        "m20",
        "Nginx reverse proxy with TLS termination in production.",
        "decision",
        ["deployment", "nginx"],
    ),
]

# (query, expected_ids) — expected_ids are the memories that SHOULD be in top results
BENCHMARK_QUERIES = [
    ("database choice", {"m01", "m07", "m13"}),
    ("caching strategy", {"m02", "m11"}),
    ("API framework", {"m03", "m16"}),
    ("authentication", {"m06"}),
    ("deployment infrastructure", {"m05", "m20"}),
    ("background jobs", {"m17"}),
    ("monitoring and observability", {"m09", "m15"}),
    ("production incidents", {"m13", "m14"}),
    ("frontend technology", {"m04"}),
    ("file uploads", {"m12"}),
]

# Paraphrase queries — should return same results as their counterpart
PARAPHRASE_QUERIES = [
    ("what database do we use", {"m01", "m07"}),
    ("how is caching done", {"m02", "m11"}),
    ("which web framework", {"m03"}),
    ("how do we handle auth", {"m06"}),
]


class FakeDistiller:
    async def distill(self, raw_text: str) -> str:
        return raw_text


@pytest.fixture
async def benchmark_store(tmp_path):
    """Create a SqliteStore populated with the benchmark dataset."""
    store = SqliteStore(str(tmp_path / "bench"), rrf_k=60)
    store.initialize()
    embedder = OllamaEmbedder(model=_MODEL)

    for mid, content, mtype, tags in MEMORIES:
        mem = Memory(
            id=mid,
            content=content,
            type=mtype,
            repos=["benchmark-repo"],
            tags=tags,
            author=None,
            created_at=datetime.now(UTC) - timedelta(days=5),
        )
        vec = await embedder.embed(content)
        await store.save(mem, vec)

    return store, embedder


@pytest.fixture
def benchmark_service(benchmark_store):
    store, embedder = benchmark_store
    return MemoryService(
        storage=store,
        embedder=embedder,
        distiller=FakeDistiller(),
        distill_enabled=False,
    )


def recall_at_k(expected: set[str], results: list, k: int) -> float:
    """Fraction of expected IDs found in the top-k results."""
    top_k_ids = {r.id for r in results[:k]}
    if not expected:
        return 1.0
    return len(expected & top_k_ids) / len(expected)


class TestRetrievalBenchmark:
    async def test_recall_at_5(self, benchmark_service) -> None:
        """At least 70% average recall@5 across benchmark queries."""
        recalls = []
        for query, expected in BENCHMARK_QUERIES:
            results = await benchmark_service.search(query, top_k=5)
            r = recall_at_k(expected, results, 5)
            recalls.append(r)

        avg_recall = sum(recalls) / len(recalls)
        assert avg_recall >= 0.70, (
            f"Average recall@5 = {avg_recall:.2f}, expected >= 0.70. "
            f"Per-query: {list(zip([q for q, _ in BENCHMARK_QUERIES], recalls, strict=False))}"
        )

    async def test_recall_at_10(self, benchmark_service) -> None:
        """At least 80% average recall@10 across benchmark queries."""
        recalls = []
        for query, expected in BENCHMARK_QUERIES:
            results = await benchmark_service.search(query, top_k=10)
            r = recall_at_k(expected, results, 10)
            recalls.append(r)

        avg_recall = sum(recalls) / len(recalls)
        assert avg_recall >= 0.80, (
            f"Average recall@10 = {avg_recall:.2f}, expected >= 0.80. "
            f"Per-query: {list(zip([q for q, _ in BENCHMARK_QUERIES], recalls, strict=False))}"
        )

    async def test_paraphrase_consistency(self, benchmark_service) -> None:
        """Paraphrased queries should return at least one expected memory."""
        for query, expected in PARAPHRASE_QUERIES:
            results = await benchmark_service.search(query, top_k=5)
            result_ids = {r.id for r in results}
            overlap = expected & result_ids
            assert len(overlap) >= 1, (
                f"Paraphrase query '{query}' returned {result_ids}, "
                f"expected at least one of {expected}"
            )

    async def test_unrelated_query_no_false_positives(self, benchmark_service) -> None:
        """Unrelated queries should not return high-confidence results."""
        unrelated = "recipe for chocolate cake"
        results = await benchmark_service.search(unrelated, top_k=5)
        # All results should have low scores (below 0.5)
        for r in results:
            assert r.score < 0.5, (
                f"Unrelated query '{unrelated}' returned '{r.snippet}' "
                f"with score {r.score:.3f}"
            )
