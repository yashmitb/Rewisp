

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


def test_forgetting_a_wisp_removes_a_pinned_answer_built_from_it(tmp_path, monkeypatch):
    """A pinned fact is kept forever by design, which makes it the one place a
    forgotten wisp could survive indefinitely — as a deterministic answer, no
    less. Regression for the gap documented in v0.18.6."""
    import json

    from rewisp import config, db

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    conn = db.connect()
    a = db.insert_capture(conn, "Dia", "p", None, "my locker code is 4417")
    b = db.insert_capture(conn, "Dia", "q", None, "unrelated text")
    conn.execute(
        "INSERT INTO pinned (question, answer, created_at, source_wisp_ids) "
        "VALUES ('what is my locker code', '4417', datetime('now'), ?)",
        (json.dumps([a]),))
    conn.execute(
        "INSERT INTO pinned (question, answer, created_at, source_wisp_ids) "
        "VALUES ('something else', 'x', datetime('now'), ?)",
        (json.dumps([b]),))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM pinned").fetchone()[0] == 2

    db.delete_captures(conn, [a])

    rows = conn.execute("SELECT question FROM pinned").fetchall()
    assert len(rows) == 1, "the pin built from the forgotten wisp should be gone"
    assert rows[0][0] == "something else", "unrelated pins must survive"


def test_pins_without_provenance_are_left_alone(tmp_path, monkeypatch):
    """Pins created before provenance tracking have no sources recorded. Deleting
    them on a guess would remove facts the user relies on."""
    from rewisp import config, db

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    conn = db.connect()
    w = db.insert_capture(conn, "Dia", "p", None, "text")
    conn.execute("INSERT INTO pinned (question, answer, created_at) "
                 "VALUES ('old pin', 'value', datetime('now'))")
    conn.commit()
    db.delete_captures(conn, [w])
    assert conn.execute("SELECT COUNT(*) FROM pinned").fetchone()[0] == 1
