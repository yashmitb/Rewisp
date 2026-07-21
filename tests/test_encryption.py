"""Encryption at rest, and every way it must refuse to lose your data.

The input is months of someone's memory with no second copy, so most of these
tests are about what happens when something goes wrong rather than when it works.
"""

import sqlite3

import pytest

from rewisp import config, crypto


@pytest.fixture(autouse=True)
def scratch(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "rewisp.db")
    monkeypatch.setattr(config, "VAULT_DIR", tmp_path / "vault")
    crypto.forget_cached_key()
    yield
    crypto.forget_cached_key()


class TestHeaderDetection:
    def test_plaintext_database_is_recognised(self, tmp_path):
        p = tmp_path / "plain.db"
        sqlite3.connect(p).execute("CREATE TABLE t(x)")
        assert not crypto.is_encrypted(p)

    def test_missing_file_is_not_encrypted(self, tmp_path):
        assert not crypto.is_encrypted(tmp_path / "nope.db")

    def test_empty_file_is_not_encrypted(self, tmp_path):
        p = tmp_path / "empty.db"
        p.touch()
        assert not crypto.is_encrypted(p)

    def test_random_bytes_read_as_encrypted(self, tmp_path):
        p = tmp_path / "enc.db"
        p.write_bytes(b"\x94\xe6\xfc\x00y\x19\xe9;\xb3\x9e\xb8\xd1" * 4)
        assert crypto.is_encrypted(p)


class TestFailsSafe:
    """Encryption must never be the reason someone can't open their memory."""

    def test_no_keychain_means_plaintext_not_a_crash(self, monkeypatch):
        from rewisp import db

        monkeypatch.setattr(crypto, "_keychain_get", lambda: None)
        monkeypatch.setattr(crypto, "_keychain_set", lambda k: False)
        conn = db.connect()
        conn.execute("SELECT COUNT(*) FROM captures")
        conn.close()
        assert not crypto.is_encrypted(config.DB_PATH)

    def test_a_key_that_cannot_be_read_back_is_refused(self, monkeypatch):
        """Storing a key we can't retrieve would encrypt the database and lock
        the user out of it permanently. Better to stay plaintext."""
        monkeypatch.setattr(crypto, "_keychain_get", lambda: None)
        monkeypatch.setattr(crypto, "_keychain_set", lambda k: True)
        assert crypto.get_key(create=True) is None

    def test_get_key_does_not_create_when_asked_not_to(self, monkeypatch):
        monkeypatch.setattr(crypto, "_keychain_get", lambda: None)
        called = []
        monkeypatch.setattr(crypto, "_keychain_set", lambda k: called.append(k) or True)
        assert crypto.get_key(create=False) is None
        assert not called, "must not mint a key when create=False"

    def test_encrypted_db_without_a_key_refuses_rather_than_recreating(self, monkeypatch):
        """The dangerous case: if this returned a fresh empty database, the user
        would open Rewisp to find their entire history apparently gone."""
        from rewisp import db

        config.DB_PATH.write_bytes(b"\x94\xe6\xfc\x00encrypted-looking" * 8)
        monkeypatch.setattr(crypto, "_keychain_get", lambda: None)
        monkeypatch.setattr(crypto, "_keychain_set", lambda k: False)
        with pytest.raises(RuntimeError, match="encrypted"):
            db.connect()

    def test_key_is_256_bits(self, monkeypatch):
        store = {}
        monkeypatch.setattr(crypto, "_keychain_get", lambda: store.get("k"))
        monkeypatch.setattr(crypto, "_keychain_set",
                            lambda k: store.__setitem__("k", k) or True)
        key = crypto.get_key(create=True)
        assert key and len(key) == 64, "32 bytes, hex encoded"
        int(key, 16)

    def test_key_is_cached_not_refetched(self, monkeypatch):
        calls = []
        monkeypatch.setattr(crypto, "_keychain_get",
                            lambda: calls.append(1) or "a" * 64)
        crypto.get_key()
        crypto.get_key()
        assert len(calls) == 1


class TestNormalUseIsUnaffected:
    def test_everything_still_works_through_connect(self):
        from rewisp import db

        conn = db.connect()
        rid = db.insert_capture(conn, "Dia", "a page", None, "burnout and exhaustion")
        assert rid
        hit = conn.execute(
            "SELECT COUNT(*) FROM captures_fts WHERE captures_fts MATCH 'exhaustion'"
        ).fetchone()[0]
        assert hit == 1, "search must work regardless of encryption state"
        conn.close()
