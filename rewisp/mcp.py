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
import pathlib
import sys

from . import config, db

log = logging.getLogger("rewisp")

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "rewisp", "version": "0.22.0"}

# The MCP server runs as a separate short-lived process spawned by the client, so
# the menu-bar app can't see it directly. It records a heartbeat here on every
# meaningful event; the UI polls /mcp-status to show "Connected · last queried…".
ACTIVITY_PATH = config.DATA_DIR / ".mcp_activity.json"


def _record(event_type: str, event: str, tool: str | None = None) -> None:
    try:
        if event_type not in ["connected", "disconnected", "tool_call", "tool_result"]:
            raise ValueError("Invalid event type")
        cur = {}
        if ACTIVITY_PATH.exists():
            cur = json.loads(ACTIVITY_PATH.read_text())
        cur["last_seen"] = db.utcnow()
        cur["last_event"] = event
        if tool:
            cur["last_tool"] = tool
            cur["calls"] = int(cur.get("calls", 0)) + 1
        if event_type == "connected":
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
