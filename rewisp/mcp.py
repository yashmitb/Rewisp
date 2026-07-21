"""MCP server — expose Rewisp's memory to external AI agents.

`python3 -m rewisp mcp` speaks the Model Context Protocol over stdio, so Claude
Code / Claude Desktop / any MCP client can query your screen memory as tools:

    claude mcp add rewisp -- python3 -m rewisp mcp

Design constraints, deliberately:
- READ-ONLY. No tool can write, delete, or change settings.
- LOCAL-ONLY. stdio transport — the client spawns us; there is no listener.
- NO CLOUD CALLS. The caller is already an AI; tools return retrieval context
  and deterministic facts for it to reason over. Rewisp's engine chain is never
  triggered, so an outside agent can never spend your subscriptions.
- VAULT EXCLUDED. Screen memory is queryable; your identity documents are not
  (flip `mcp_expose_vault` in settings.json if you ever want them).

The protocol surface is small (initialize / tools/list / tools/call / ping),
so this is a dependency-free JSON-RPC loop rather than an SDK.
"""

import json
import logging
import re
import sys

from . import config, db

log = logging.getLogger("rewisp")

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "rewisp", "version": "0.20.0"}

# The MCP server runs as a separate short-lived process spawned by the client, so
# the menu-bar app can't see it directly. It records a heartbeat here on every
# meaningful event; the UI polls /mcp-status to show "Connected · last queried…".
ACTIVITY_PATH = config.DATA_DIR / ".mcp_activity.json"


def _record(event: str, tool: str | None = None) -> None:
    try:
        cur = {}
        if ACTIVITY_PATH.exists():
            cur = json.loads(ACTIVITY_PATH.read_text())
        cur["last_seen"] = db.utcnow()
        cur["last_event"] = event
        if tool:
            cur["last_tool"] = tool
            cur["calls"] = int(cur.get("calls", 0)) + 1
        if event == "connected":
            cur["client"] = cur.get("client")     # filled from initialize params
        config.ensure_dirs()
        ACTIVITY_PATH.write_text(json.dumps(cur))
    except Exception:  # noqa: BLE001 — telemetry-ish, never fail a request over it
        pass

# ── tools ─────────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "search_memory",
        "description": (
            "Search the user's screen memory (everything they've seen on their Mac, "
            "stored as text). Hybrid keyword + semantic search. Returns matching "
            "moments with app, time (UTC), and a text snippet. Use for 'did the user "
            "see / read / visit X', or to find a specific fact they encountered."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for (plain language works)"},
                "since": {"type": "string", "description": "Optional ISO date/datetime lower bound (UTC)"},
                "until": {"type": "string", "description": "Optional ISO date/datetime upper bound (UTC)"},
                "limit": {"type": "integer", "description": "Max results (default 8, max 20)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_context",
        "description": (
            "Build the full retrieval context Rewisp would use to answer a question "
            "about the user's digital life: deterministic facts (pinned answers, "
            "tracked numbers, page diffs), matching screen moments, and daily "
            "summaries. Returns context for YOU to reason over — call this first "
            "when answering questions about what the user did, saw, or was told."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The user's question, verbatim"},
            },
            "required": ["question"],
        },
    },
    {
        "name": "get_day_summary",
        "description": ("The digest summary for a day: what happened, loose threads, "
                        "and minutes-per-app. Defaults to the most recent digest."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD (optional; default latest)"},
            },
        },
    },
    {
        "name": "get_promises",
        "description": ("Open commitments Rewisp caught off the user's screen — what "
                        "they said they'd do (with deadlines), and what they're "
                        "waiting on from others."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_page_changes",
        "description": ("Diff two versions of a page the user visits repeatedly: what "
                        "was added, removed, or changed since they last looked. "
                        "page_key is a URL (query params ignored) or 'app::window title'."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_key": {"type": "string", "description": "URL or app::title of the page"},
            },
            "required": ["page_key"],
        },
    },
]


def _fmt_rows(rows: list[dict]) -> str:
    out = []
    for r in rows:
        loc = r.get("url") or r.get("window_title") or ""
        snip = " ".join((r.get("snippet") or "").split())
        out.append(f"[{r['ts']} UTC · {r['app']}{' · ' + loc if loc else ''}]\n{snip}")
    return "\n\n".join(out) if out else "No matching moments."


def t_search_memory(args: dict) -> str:
    conn = db.connect()
    try:
        from . import embed
        from .ask import _fts_query
        q = (args.get("query") or "").strip()
        if not q:
            return "Empty query."
        limit = min(int(args.get("limit") or 8), 20)
        qvec = embed.embed_vec(q)
        rows = db.search_captures_hybrid(
            conn, _fts_query(q), qvec, limit=limit,
            since=args.get("since"), until=args.get("until"))
        return _fmt_rows(rows)
    finally:
        conn.close()


def _strip_vault(ctx: str) -> str:
    """Remove the Vault section (and any stray [vault:...] chunk) from context.
    Section-based, not char-class: vault files contain '#' (LaTeX, markdown), so a
    negated-char regex under-matched and leaked identity data."""
    blocks = re.split(r"(?=^## )", ctx, flags=re.M)
    kept = [b for b in blocks
            if not b.lstrip().lower().startswith("## vault")
            and "[vault:" not in b.lower()]
    return "".join(kept)


def t_get_context(args: dict) -> str:
    conn = db.connect()
    try:
        from . import ask, forgetting, numbers
        question = (args.get("question") or "").strip()
        if not question:
            return "Empty question."
        parts = []
        # Deterministic facts first — exact, no model needed. (vault_fact is
        # intentionally NOT consulted unless the user opted the Vault in.)
        det = (forgetting.pinned_answer(conn, question)
               or ask.delta_answer(conn, question)
               or numbers.lookup(conn, question))
        if det is None and config.load_settings().get("mcp_expose_vault", False):
            det = ask.vault_fact(conn, question)
        if det:
            parts.append("## Exact answer (deterministic — trust this)\n"
                         + det["answer"]
                         + (f"\n{det['detail']}" if det.get("detail") else ""))
        ctx, meta = ask.build_context(conn, question, compact=False)
        if not config.load_settings().get("mcp_expose_vault", False):
            ctx = _strip_vault(ctx)     # identity documents stay out of MCP
        parts.append("## Retrieval context (screen memory)\n" + ctx.strip())
        if meta.get("since"):
            parts.append(f"(time window applied: {meta['since']} → {meta['until']} UTC)")
        return "\n\n".join(parts)
    finally:
        conn.close()


def t_get_day_summary(args: dict) -> str:
    conn = db.connect()
    try:
        date = (args.get("date") or "").strip()
        if date:
            row = conn.execute(
                "SELECT date, summary_md, threads_md, time_report_json FROM summaries "
                "WHERE date = ?", (date,)).fetchone()
        else:
            row = conn.execute(
                "SELECT date, summary_md, threads_md, time_report_json FROM summaries "
                "ORDER BY date DESC LIMIT 1").fetchone()
        if not row:
            return "No digest for that day."
        d, summary, threads, report = row
        out = [f"# {d}", summary or "(no summary)"]
        if threads and threads.strip() not in ("", "None."):
            out.append("## Loose threads\n" + threads)
        try:
            times = json.loads(report or "{}")
            top = sorted(times.items(), key=lambda kv: -kv[1])[:6]
            if top:
                out.append("## Minutes per app\n" +
                           "\n".join(f"- {app}: {m} min" for app, m in top if m))
        except (json.JSONDecodeError, TypeError):
            pass
        return "\n\n".join(out)
    finally:
        conn.close()


def t_get_promises(args: dict) -> str:
    conn = db.connect()
    try:
        rows = db.promises_by_status(conn, ("pending", "confirmed"))
        if not rows:
            return "No open promises."
        out = []
        for p in rows:
            lane = "user owes" if p["who"] == "me" else "waiting on them"
            due = f", due {p['due']}" if p.get("due") else ""
            out.append(f"- [{lane}{due}] {p['what']} ({p['status']})")
        return "\n".join(out)
    finally:
        conn.close()


def t_get_page_changes(args: dict) -> str:
    conn = db.connect()
    try:
        from . import delta
        raw = (args.get("page_key") or "").strip()
        if not raw:
            return "Empty page_key."
        key = delta.page_key(None, None, raw) if raw.startswith("http") else raw.lower()
        old, new = db.versions_for_key(conn, key)
        if not new:
            return f"No captures for page_key {key!r}."
        if not old:
            return "Only one version captured — nothing to diff yet."
        d = delta.diff_texts(old["ocr_text"], new["ocr_text"])
        out = [delta.summarize(d), f"({old['ts']} → {new['ts']} UTC)"]
        for x in d["added"][:10]:
            out.append(f"+ {x}")
        for c in d["changed"][:10]:
            out.append(f"~ {c['old']}  →  {c['new']}")
        for x in d["removed"][:10]:
            out.append(f"− {x}")
        return "\n".join(out)
    finally:
        conn.close()


HANDLERS = {
    "search_memory": t_search_memory,
    "get_context": t_get_context,
    "get_day_summary": t_get_day_summary,
    "get_promises": t_get_promises,
    "get_page_changes": t_get_page_changes,
}

# ── JSON-RPC over stdio ───────────────────────────────────────────────────────

# ── one-click install into MCP clients ───────────────────────────────────────

def _package_dir() -> str:
    """Directory that CONTAINS the `rewisp` package (so python -m rewisp works)."""
    from pathlib import Path
    return str(Path(__file__).resolve().parent.parent)


def server_entry() -> dict:
    """The mcpServers config block every client understands. Uses this exact
    interpreter (it has the deps) and points PYTHONPATH at the package dir."""
    return {
        "command": sys.executable,
        "args": ["-m", "rewisp", "mcp"],
        "env": {"PYTHONPATH": _package_dir()},
    }


def cli_command() -> str:
    return (f'claude mcp add rewisp -e PYTHONPATH="{_package_dir()}" '
            f'-- "{sys.executable}" -m rewisp mcp')


def client_setups() -> list[dict]:
    """Per-client setup instructions. Most MCP clients read a JSON config with an
    `mcpServers` block; VS Code uses `servers` with an explicit type. CLIs get a
    one-liner. Everything is generated from the one canonical server entry."""
    entry = server_entry()
    mcp_json = json.dumps({"mcpServers": {"rewisp": entry}}, indent=2)
    home = str(config.HOME)
    return [
        {"name": "Claude Desktop", "icon": "menubar.dock.rectangle", "kind": "button",
         "text": mcp_json,
         "where": "~/Library/Application Support/Claude/claude_desktop_config.json",
         "note": "One click below writes it for you. Then quit and reopen Claude Desktop."},
        {"name": "Claude Code", "icon": "terminal.fill", "kind": "cli",
         "text": cli_command(),
         "where": "Run in Terminal.",
         "note": "Then just talk to Claude Code — it'll use the tools automatically."},
        {"name": "Cursor", "icon": "cursorarrow.rays", "kind": "config",
         "text": mcp_json, "where": f"{home}/.cursor/mcp.json",
         "note": "Create/merge this file, then reload Cursor. Also visible in Cursor → Settings → MCP."},
        {"name": "Windsurf", "icon": "wind", "kind": "config",
         "text": mcp_json, "where": f"{home}/.codeium/windsurf/mcp_config.json",
         "note": "Create/merge this file, then reload Windsurf."},
        {"name": "VS Code", "icon": "chevron.left.forwardslash.chevron.right", "kind": "config",
         "text": json.dumps({"servers": {"rewisp": {"type": "stdio", **entry}}}, indent=2),
         "where": ".vscode/mcp.json (in your workspace)",
         "note": "VS Code uses `servers` + a stdio type. Needs GitHub Copilot / Agent mode."},
        {"name": "Gemini CLI", "icon": "sparkle", "kind": "config",
         "text": mcp_json, "where": f"{home}/.gemini/settings.json",
         "note": "Merge into your Gemini CLI settings under mcpServers."},
        {"name": "ChatGPT", "icon": "bubble.left.and.bubble.right", "kind": "note",
         "text": "", "where": "",
         "note": "ChatGPT's connectors accept only REMOTE MCP servers (a public https URL). Rewisp is local by design (your memory never leaves the Mac), so it can't be added to ChatGPT without exposing a server to the internet — not recommended."},
        {"name": "Other client", "icon": "curlybraces", "kind": "config",
         "text": mcp_json, "where": "your client's MCP config",
         "note": "Any client that reads an `mcpServers` block will work with this."},
    ]


def desktop_config_path():
    return (config.HOME / "Library" / "Application Support" / "Claude"
            / "claude_desktop_config.json")


def desktop_installed() -> bool:
    p = desktop_config_path()
    if not p.exists():
        return False
    try:
        return "rewisp" in (json.loads(p.read_text()).get("mcpServers") or {})
    except (ValueError, OSError):
        return False


def install_to_desktop() -> dict:
    """Merge the rewisp server into Claude Desktop's config (creating it if
    needed). Non-destructive — preserves any other configured servers."""
    p = desktop_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cfg = {}
    if p.exists():
        try:
            cfg = json.loads(p.read_text())
        except ValueError:
            cfg = {}
    cfg.setdefault("mcpServers", {})["rewisp"] = server_entry()
    p.write_text(json.dumps(cfg, indent=2))
    return {"ok": True, "path": str(p)}


def _reply(msg_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


def handle(msg: dict) -> None:
    method = msg.get("method")
    msg_id = msg.get("id")
    if method == "initialize":
        params = msg.get("params", {})
        client = (params.get("clientInfo") or {}).get("name")
        try:
            cur = json.loads(ACTIVITY_PATH.read_text()) if ACTIVITY_PATH.exists() else {}
            cur["client"] = client or cur.get("client")
            config.ensure_dirs(); ACTIVITY_PATH.write_text(json.dumps(cur))
        except Exception:  # noqa: BLE001
            pass
        _record("connected")
        _reply(msg_id, {
            "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    elif method == "notifications/initialized":
        pass                                        # notification — no reply
    elif method == "ping":
        _reply(msg_id, {})
    elif method == "tools/list":
        _reply(msg_id, {"tools": TOOLS})
    elif method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name")
        fn = HANDLERS.get(name)
        if fn is None:
            _reply(msg_id, error={"code": -32602, "message": f"unknown tool {name!r}"})
            return
        try:
            text = fn(params.get("arguments") or {})
            _record("call", tool=name)
            _reply(msg_id, {"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as e:  # noqa: BLE001 — report, don't crash the server
            log.exception("mcp tool %s failed", name)
            _reply(msg_id, {"content": [{"type": "text", "text": f"tool error: {e}"}],
                            "isError": True})
    elif msg_id is not None:
        _reply(msg_id, error={"code": -32601, "message": f"method {method!r} not supported"})


def serve() -> None:
    """Blocking stdio loop. One JSON-RPC message per line."""
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    log.warning("rewisp mcp server ready (read-only, vault %s)",
                "EXPOSED" if config.load_settings().get("mcp_expose_vault") else "excluded")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            handle(msg)
        except Exception:  # noqa: BLE001
            log.exception("mcp: handler crashed")
