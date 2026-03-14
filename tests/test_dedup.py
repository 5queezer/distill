"""Dedup — cosine similarity gate. If this is wrong, duplicates leak or valid entries get blocked."""

import math

from distill_mcp.dedup import cosine_similarity


def _vec(seed: float) -> list[float]:
    return [math.sin(seed * 100.0 + i) for i in range(768)]


def test_identical_vectors_rejected() -> None:
    v = _vec(0.5)
    assert cosine_similarity(v, v) > 0.99


def test_near_identical_rejected() -> None:
    v = _vec(0.5)
    noisy = [x + 0.001 for x in v]
    assert cosine_similarity(v, noisy) > 0.95


def test_different_vectors_accepted() -> None:
    assert cosine_similarity(_vec(0.1), _vec(0.9)) < 0.95
