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
SERVER_INFO = {"name": "rewisp", "version": "0.23.0"}

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


def _runtime_env() -> dict:
    """Environment an MCP client must set to run the bundled interpreter.

    PYTHONHOME is not optional and its absence is not subtle: the shipped
    interpreter lives in RewispBackend.app while its standard library sits in
    Resources/python, so without it the process dies instantly with "Failed to
    import encodings module" and the client reports only "Server disconnected".
    Every client using a config written before this fix hit exactly that.

    PYTHONPYCACHEPREFIX is belt and braces. A stray interpreter run without it
    writes __pycache__ inside the app bundle, which invalidates the code
    signature and makes macOS withdraw Screen Recording — the v0.17.2 bug. The
    bundled sitecustomize already refuses bytecode writes, but an MCP client is
    exactly the kind of caller that would otherwise reintroduce it.
    """
    exe = pathlib.Path(sys.executable)
    env = {"PYTHONPATH": _package_dir()}
    # .../Rewisp.app/Contents/MacOS/RewispBackend.app/Contents/MacOS/Rewisp Backend
    #  -> .../Rewisp.app/Contents/Resources/python
    for parent in exe.parents:
        candidate = parent / "Resources" / "python"
        if (candidate / "lib").is_dir():
            env["PYTHONHOME"] = str(candidate)
            break
    env["PYTHONPYCACHEPREFIX"] = str(config.DATA_DIR / ".pycache")
    return env


def server_entry() -> dict:
    """The mcpServers config block every client understands."""
    return {
        "command": sys.executable,
        "args": ["-m", "rewisp", "mcp"],
        "env": _runtime_env(),
    }


def cli_command() -> str:
    envs = " ".join(f'-e {k}="{v}"' for k, v in _runtime_env().items())
    return f'claude mcp add rewisp {envs} -- "{sys.executable}" -m rewisp mcp'


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
         "text": mcp_json, "where": f"{home}/.cursor/mcp.json", "install": "cursor",
         "note": "Then quit and reopen Cursor. You'll see Rewisp under Settings → MCP."},
        {"name": "Windsurf", "icon": "wind", "kind": "config",
         "text": mcp_json, "where": f"{home}/.codeium/windsurf/mcp_config.json",
         "install": "windsurf",
         "note": "Then quit and reopen Windsurf."},
        {"name": "VS Code", "icon": "chevron.left.forwardslash.chevron.right", "kind": "config",
         "text": json.dumps({"servers": {"rewisp": {"type": "stdio", **entry}}}, indent=2),
         "where": ".vscode/mcp.json (inside your project folder)",
         "note": "VS Code keeps this per-project, so Rewisp can't place it for you. "
                 "Make a .vscode folder in your project, put this in mcp.json, reload "
                 "VS Code. Needs GitHub Copilot in Agent mode."},
        {"name": "Gemini CLI", "icon": "sparkle", "kind": "config",
         "text": mcp_json, "where": f"{home}/.gemini/settings.json",
         "install": "gemini-cli",
         "note": "Then close and reopen Gemini CLI. Ask it \"what tools do you have?\" to check."},
        {"name": "ChatGPT", "icon": "bubble.left.and.bubble.right", "kind": "note",
         "text": "", "where": "",
         "note": "ChatGPT's connectors accept only REMOTE MCP servers (a public https URL). Rewisp is local by design (your memory never leaves the Mac), so it can't be added to ChatGPT without exposing a server to the internet — not recommended."},
        {"name": "Other client", "icon": "curlybraces", "kind": "config",
         "text": mcp_json, "where": "your client's MCP config file",
         "note": "Any client that reads an mcpServers block works. Paste this into "
                 "its config file (not a terminal), then restart it."},
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


# Where each client keeps its MCP config, and which root key it uses. VS Code is
# the odd one out: `servers`, not `mcpServers`, and its file is workspace-relative
# so there is no single path to write.
INSTALL_TARGETS = {
    "claude-desktop": {"path": lambda: desktop_config_path(), "key": "mcpServers"},
    "cursor":         {"path": lambda: config.HOME / ".cursor" / "mcp.json",
                       "key": "mcpServers"},
    "windsurf":       {"path": lambda: config.HOME / ".codeium" / "windsurf" / "mcp_config.json",
                       "key": "mcpServers"},
    "gemini-cli":     {"path": lambda: config.HOME / ".gemini" / "settings.json",
                       "key": "mcpServers"},
}


def install_for(client: str) -> dict:
    """Merge the rewisp server into a client's config file.

    Non-destructive, and defensively so: these files belong to the user's editor,
    not to us. A previous version parsed the file and fell back to `{}` when the
    JSON was malformed, which silently overwrote every other MCP server they had
    configured. Now a file we cannot parse is backed up and refused, because
    destroying someone's editor config to add ourselves is never the right trade.
    """
    target = INSTALL_TARGETS.get(client)
    if not target:
        return {"ok": False, "error": f"No automatic setup for {client!r}."}

    p = target["path"]()
    key = target["key"]
    cfg: dict = {}

    if p.exists() and p.stat().st_size:
        raw = p.read_text()
        try:
            cfg = json.loads(raw)
            if not isinstance(cfg, dict):
                raise ValueError("top level is not an object")
        except ValueError as e:
            backup = p.with_suffix(p.suffix + ".rewisp-backup")
            try:
                backup.write_text(raw)
            except OSError:
                pass
            return {"ok": False, "path": str(p), "backup": str(backup),
                    "error": f"That file isn't valid JSON ({e}), so Rewisp didn't "
                             f"touch it — editing it automatically could have wiped "
                             f"your other servers. A copy is saved alongside it."}

    existing = cfg.get(key)
    if existing is not None and not isinstance(existing, dict):
        return {"ok": False, "path": str(p),
                "error": f"'{key}' in that file isn't an object, so Rewisp left it alone."}

    others = sorted(k for k in (existing or {}) if k != "rewisp")
    cfg.setdefault(key, {})["rewisp"] = server_entry()

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # Write via a temp file in the same directory, then replace: a crash
        # mid-write must not leave a half-written config behind.
        tmp = p.with_suffix(p.suffix + ".rewisp-tmp")
        tmp.write_text(json.dumps(cfg, indent=2) + "\n")
        tmp.replace(p)
    except OSError as e:
        return {"ok": False, "path": str(p), "error": f"Couldn't write it: {e}"}

    return {"ok": True, "path": str(p), "kept": others}


def test_connection() -> dict:
    """Launch the server exactly as a client would and report what came back.

    Two separate users reported "Server disconnected" and had no way to tell
    whether setup had worked. The answer lived in a handshake nobody could run.
    Critically this launches from the CONFIG we generate, with a clean
    environment, because the bug that caused both reports was a config that
    looked right and pointed at an interpreter that could not start — testing the
    server directly, with a helpful environment, is what hid it.
    """
    import os
    import subprocess

    entry = server_entry()
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TMPDIR", "USER")}
    env.update(entry.get("env") or {})
    handshake = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                   "clientInfo": {"name": "rewisp-selftest", "version": "1"}}})
    listing = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    try:
        p = subprocess.run([entry["command"]] + entry["args"],
                           input=handshake + "\n" + listing + "\n",
                           capture_output=True, text=True, timeout=45, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": f"Couldn't start the server: {e}"}

    tools: list[str] = []
    for line in (p.stdout or "").splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("id") == 2 and isinstance(msg.get("result"), dict):
            tools = [t["name"] for t in msg["result"].get("tools", [])]

    if tools:
        return {"ok": True, "tools": tools, "count": len(tools)}
    err = (p.stderr or "").strip().splitlines()
    detail = err[-1] if err else "the server exited without responding"
    return {"ok": False, "exit_code": p.returncode,
            "error": f"The server didn't answer: {detail}"}


def install_to_desktop() -> dict:
    """Kept for the existing Claude Desktop button."""
    return install_for("claude-desktop")


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
