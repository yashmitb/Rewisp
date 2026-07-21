"""MCP server — protocol shape, tool handlers, and the Vault privacy guarantee."""

import io
import json

from rewisp import mcp


def _drive(messages):
    """Feed JSON-RPC messages through handle(), capture the replies."""
    import sys
    out = io.StringIO()
    old = sys.stdout
    sys.stdout = out
    try:
        for m in messages:
            mcp.handle(m)
    finally:
        sys.stdout = old
    return [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]


class TestProtocol:
    def test_initialize_handshake(self):
        r = _drive([{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2024-11-05"}}])
        assert r[0]["result"]["serverInfo"]["name"] == "rewisp"
        assert "tools" in r[0]["result"]["capabilities"]

    def test_tools_list(self):
        r = _drive([{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        names = {t["name"] for t in r[0]["result"]["tools"]}
        assert names == {"search_memory", "get_context", "get_day_summary",
                         "get_promises", "get_page_changes"}
        # every tool has a JSON schema
        for t in r[0]["result"]["tools"]:
            assert t["inputSchema"]["type"] == "object"

    def test_notification_gets_no_reply(self):
        assert _drive([{"jsonrpc": "2.0", "method": "notifications/initialized"}]) == []

    def test_unknown_tool_errors(self):
        r = _drive([{"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {"name": "delete_everything", "arguments": {}}}])
        assert "error" in r[0]

    def test_unknown_method_errors(self):
        r = _drive([{"jsonrpc": "2.0", "id": 4, "method": "resources/list"}])
        assert r[0]["error"]["code"] == -32601


class TestVaultPrivacy:
    def test_strip_vault_removes_section_with_hashes(self):
        ctx = ("## Screen captures\n[#1 Notes] real content\n\n"
               "## Vault (user-provided files — trusted truth)\n"
               "[vault:resume.md]\n# My Heading\nSSN-ish: don't leak\n\n"
               "## Daily summaries\n[summary 2026-07-18] a good day")
        out = mcp._strip_vault(ctx)
        assert "vault:" not in out.lower() and "## Vault" not in out
        assert "Screen captures" in out and "Daily summaries" in out
        assert "leak" not in out

    def test_get_context_excludes_vault_by_default(self, conn, monkeypatch):
        # Uses the fixture database, not ~/Rewisp: a test that reads real user
        # data is both a privacy problem and a source of false failures.
        from rewisp import db
        monkeypatch.setattr(db, "connect", lambda: conn)
        monkeypatch.setattr(mcp, "db", db)
        # even asking for a personal fact, no vault file chunk leaks
        ctx = mcp.t_get_context({"question": "what is my email"})
        assert "[vault:" not in ctx


class TestHandlers:
    def test_get_promises(self, conn, monkeypatch):
        from rewisp import db
        monkeypatch.setattr(mcp, "db", db)
        rid = db.insert_capture(conn, "Notes", None, None, "x")
        db.add_promise(conn, rid, "me", "send the deck", "2026-07-20", 0.9)
        db.set_promise_status(conn, 1, "confirmed")
        monkeypatch.setattr(db, "connect", lambda: conn)
        out = mcp.t_get_promises({})
        assert "send the deck" in out and "user owes" in out

    def test_get_page_changes_needs_two_versions(self, conn, monkeypatch):
        from rewisp import db
        monkeypatch.setattr(db, "connect", lambda: conn)
        conn.execute("INSERT INTO captures (ts, app, window_title, url, ocr_text, page_key) "
                     "VALUES (datetime('now'),'App','P',NULL,'only one', 'app::p')")
        conn.commit()
        assert "one version" in mcp.t_get_page_changes({"page_key": "app::p"}).lower()
