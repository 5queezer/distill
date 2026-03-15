"""RRF merge — the only non-trivial ranking logic."""

from distill_mcp.adapters.storage.sqlite_store import rrf_merge

K = 60


def test_fts_only() -> None:
    result = rrf_merge(["a", "b", "c"], [], k=K)
    ids = [mid for mid, _ in result]
    assert ids == ["a", "b", "c"]


def test_vec_only() -> None:
    result = rrf_merge([], ["x", "y"], k=K)
    ids = [mid for mid, _ in result]
    assert ids == ["x", "y"]


def test_disjoint_lists() -> None:
    result = rrf_merge(["a", "b"], ["x", "y"], k=K)
    # a and x both rank 1 in their lists → same score → either order is fine
    # b and y both rank 2 → same score
    ids = [mid for mid, _ in result]
    assert set(ids[:2]) == {"a", "x"}
    assert set(ids[2:]) == {"b", "y"}


def test_overlap_boosted() -> None:
    """ID appearing in both lists gets a higher RRF score than single-list IDs."""
    result = rrf_merge(["shared", "a"], ["shared", "x"], k=K)
    ids = [mid for mid, _ in result]
    assert ids[0] == "shared"


def test_empty_inputs() -> None:
    assert rrf_merge([], [], k=K) == []
