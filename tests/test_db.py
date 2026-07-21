

def test_forgetting_a_wisp_removes_its_nudge(tmp_path, monkeypatch):
    """A nudge quotes its source wisp verbatim, so forgetting the wisp must take
    the nudge with it. Regression: nudges were added after the cascade was
    written and were not attached, so 'Forget 10 minutes' left a pill that
    repeated the forgotten text back to the user."""
    from rewisp import config, db

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    conn = db.connect()
    wisp = db.insert_capture(conn, "Dia", "a page", None, "something private")
    conn.execute(
        "INSERT INTO nudges (type, title, body, source_wisp_id, status) "
        "VALUES ('recall', 'You saw this', 'You saw this: something private', ?, 'pending')",
        (wisp,))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM nudges").fetchone()[0] == 1

    db.delete_captures(conn, [wisp])

    assert conn.execute("SELECT COUNT(*) FROM nudges").fetchone()[0] == 0, \
        "nudge outlived the wisp it quotes"
