"""Shared fixtures. An in-memory SQLite with the real schema + migrations, so
db-layer logic (retrieval, diff lookups, cascade delete, later promises/series)
is tested without touching the user's live database."""

import sqlite3

import numpy as np
import pytest

from rewisp import db


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(db.SCHEMA)
    db._migrate(c)
    yield c
    c.close()


@pytest.fixture
def unit_vec():
    """Deterministic normalized 512-dim vector from a seed (stand-in for a real
    embedding — the retrieval math only cares that vectors are unit-norm)."""
    def make(seed: int) -> bytes:
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(db_dim()).astype(np.float32)
        v /= np.linalg.norm(v)
        return v.tobytes()
    return make


def db_dim() -> int:
    from rewisp import embed
    return embed.DIM
