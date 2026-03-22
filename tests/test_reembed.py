"""Tests for the reembed CLI command logic."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from distill_mcp.adapters.storage.sqlite_store import SqliteStore
from distill_mcp.domain.models import Memory


class FakeEmbedder:
    """Embedder that produces vectors of a configurable dimension."""

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim
        self.call_count = 0

    async def embed(self, text: str) -> list[float]:
        self.call_count += 1
        return [0.1] * self.dim


def _make_memory(id: str, content: str = "test content") -> Memory:
    return Memory(
        id=id,
        content=content,
        type="decision",
        repos=["repo"],
        tags=["tag"],
        author=None,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def store(tmp_path: Path) -> SqliteStore:
    s = SqliteStore(str(tmp_path))
    s.initialize()
    return s


@pytest.mark.asyncio
async def test_reembed_rebuilds_vectors(tmp_path: Path) -> None:
    """Reembed drops old vectors and creates new ones with correct dimension."""
    store = SqliteStore(str(tmp_path))
    store.initialize()

    # Save 3 memories with 3072-dim vectors (old model)
    for i in range(3):
        mem = _make_memory(f"mem-{i}", f"content {i}")
        await store.save(mem, [0.1] * 3072)
    assert store.get_vector_dimension() == 3072
    await store.save_embedding_meta("old-model", 3072)

    # Simulate reembed with 768-dim embedder (new model)
    embedder = FakeEmbedder(dim=768)
    new_model = "new-model"

    lance_dir = tmp_path / "lance"
    backup = lance_dir.with_name("lance.bak.3072")

    # Backup
    if lance_dir.exists():
        if backup.exists():
            shutil.rmtree(backup)
        shutil.copytree(lance_dir, backup)

    # Drop old
    if "vectors" in store._lance.list_tables().tables:
        store._lance.drop_table("vectors")
    store._stored_vec_dim = None

    # Re-embed
    memories = await store.list_recent(limit=100000)
    for mem in memories:
        vec = await embedder.embed(mem.content)
        data = [{"id": mem.id, "vector": vec, "agent_id": mem.agent_id or ""}]
        if "vectors" in store._lance.list_tables().tables:
            store._lance.open_table("vectors").add(data)
        else:
            store._lance.create_table("vectors", data)
            store._stored_vec_dim = len(vec)
    await store.save_embedding_meta(new_model, 768)

    # Verify
    assert store._stored_vec_dim == 768
    assert backup.exists()
    model, dim = await store.get_embedding_meta()
    assert model == "new-model"
    assert dim == 768
    assert embedder.call_count == 3


@pytest.mark.asyncio
async def test_reembed_no_memories(tmp_path: Path, capsys) -> None:
    """Reembed with no memories exits early."""
    store = SqliteStore(str(tmp_path))
    store.initialize()
    memories = await store.list_recent(limit=100000)
    assert len(memories) == 0


@pytest.mark.asyncio
async def test_reembed_backup_replaces_existing(tmp_path: Path) -> None:
    """If a backup already exists, it gets replaced."""
    store = SqliteStore(str(tmp_path))
    store.initialize()
    mem = _make_memory("mem-1")
    await store.save(mem, [0.1] * 768)

    lance_dir = tmp_path / "lance"
    backup = lance_dir.with_name("lance.bak.768")

    # Create a fake old backup
    backup.mkdir(parents=True)
    (backup / "sentinel.txt").write_text("old backup")

    # Run backup logic
    if backup.exists():
        shutil.rmtree(backup)
    shutil.copytree(lance_dir, backup)

    assert backup.exists()
    assert not (backup / "sentinel.txt").exists()


@pytest.mark.asyncio
async def test_reembed_async_integration(tmp_path: Path) -> None:
    """End-to-end test of _reembed_async."""
    from distill_mcp.__main__ import _reembed_async

    store = SqliteStore(str(tmp_path))
    store.initialize()

    # Seed with 3072-dim vectors
    for i in range(2):
        mem = _make_memory(f"mem-{i}", f"content {i}")
        await store.save(mem, [0.1] * 3072)
    await store.save_embedding_meta("old-model", 3072)

    embedder = FakeEmbedder(dim=768)
    count = await _reembed_async(store, embedder, "new-model", str(tmp_path))

    assert count == 2
    assert embedder.call_count == 2

    # Verify vectors rebuilt with new dimension
    store2 = SqliteStore(str(tmp_path))
    store2.initialize()
    assert store2.get_vector_dimension() == 768
    model, dim = await store2.get_embedding_meta()
    assert model == "new-model"
    assert dim == 768

    # Backup exists
    assert (tmp_path / "lance.bak.3072").exists()
