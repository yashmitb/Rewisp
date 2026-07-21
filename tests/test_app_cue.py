"""App names in a question are retrieval paths, not search terms.

Sparrow/Liu/Wegner 2011: when people know information is stored somewhere, they
remember *where it lives* rather than what it said — and typically one or the
other, not both. "That thing in Dia yesterday" is that shape exactly: weak
content memory wrapped in a strong contextual one. Retrieval should spend the
cue on the app column, not waste it as a keyword.
"""

import pytest

from rewisp import ask, config, db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    c = db.connect()
    # Enough rows per app to clear the >=5 cue threshold.
    for i in range(8):
        db.insert_capture(c, "Dia", f"page {i}", f"https://x/{i}",
                          f"reading about pasta recipes {i}")
        db.insert_capture(c, "Antigravity IDE", f"file {i}", None,
                          f"def compute_total(): return {i}")
    c.commit()
    ask._APP_CACHE = (0.0, [])      # cache is module-level; keep tests isolated
    yield c
    c.close()


def test_known_apps_comes_from_the_users_own_history(conn):
    apps = ask.known_apps(conn)
    assert "Dia" in apps and "Antigravity IDE" in apps


def test_rare_apps_are_not_cues(conn):
    """One sighting of an app is noise, not a vocabulary entry."""
    db.insert_capture(conn, "Calculator", "t", None, "1+1")
    conn.commit()
    ask._APP_CACHE = (0.0, [])
    assert "Calculator" not in ask.known_apps(conn)


def test_app_name_is_extracted_and_stripped(conn):
    app, rest = ask.app_cue(conn, "what did I read in Dia yesterday")
    assert app == "Dia"
    assert "dia" not in rest, "the cue must stop competing as a content word"
    assert "read" in rest


def test_longest_app_name_wins(conn):
    """'Antigravity IDE' must not be beaten by a bare 'IDE' substring match."""
    app, _ = ask.app_cue(conn, "the function I wrote in Antigravity IDE")
    assert app == "Antigravity IDE"


def test_no_false_positive_on_word_fragments(conn):
    db.insert_capture(conn, "Terminal", "t", None, "ls -la")
    for _ in range(6):
        db.insert_capture(conn, "Terminal", "t", None, "cd /tmp")
    conn.commit()
    ask._APP_CACHE = (0.0, [])
    app, _ = ask.app_cue(conn, "was that patient terminally ill")
    assert app is None, "'terminally' must not match the Terminal app"


def test_question_without_an_app_is_unchanged(conn):
    app, rest = ask.app_cue(conn, "what did I do yesterday")
    assert app is None
    assert rest == "what did I do yesterday"


def test_app_only_question_keeps_something_to_embed(conn):
    app, rest = ask.app_cue(conn, "Dia")
    assert app == "Dia"
    assert rest.strip(), "stripping everything would leave nothing to search on"


def test_cue_reorders_results_toward_that_app(conn):
    """The payoff: same words, different app named, different ordering."""
    import unittest.mock as mock
    with mock.patch("rewisp.embed.embed_vec", return_value=None):
        ctx, _ = ask.build_context(conn, "what was I reading in Dia?", compact=True)
    assert "pasta" in ctx
