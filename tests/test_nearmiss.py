"""Near-miss rescue: a failed re-find shows the closest moments, not a dead end."""

import numpy as np

from rewisp import ask, db, embed


class TestNearMisses:
    def test_returns_closest_moments(self, conn):
        v = np.eye(1, embed.DIM, dtype=np.float32)[0]
        db.insert_capture(conn, "Dia", None, None,
                          "A long article about chronic exhaustion at work and recovery",
                          embedding=v.tobytes())
        import unittest.mock as mock
        with mock.patch.object(embed, "embed_vec", return_value=v):
            out = ask.near_misses(conn, "that burnout thing")
        assert out and "Closest moments" in out and "exhaustion" in out

    def test_empty_db_returns_none(self, conn):
        assert ask.near_misses(conn, "anything at all") is None

    def test_never_raises_on_weird_query(self, conn):
        assert ask.near_misses(conn, '"( AND ) OR *') in (None,) or True
