"""Localhost HTTP API for the native UI. Binds 127.0.0.1 only — nothing leaves the machine.

Every request must carry the shared secret in X-Rewisp-Token (file ~/Rewisp/.api_token,
mode 0600). Without it, any local process could read the whole screen history.

GET  /status          -> daemon state, today's counts, digest info
GET  /recap           -> "today so far" (local heuristics before Digest, Digest after)
GET  /threads         -> current loose threads (latest summary)
GET  /memory          -> confirmed + pending memory lines
GET  /chats           -> recent ask history (for the Chat tab)
GET  /vault           -> vault file listing
GET  /killlist        -> defaults (read-only) + user additions
POST /ask             -> {"question": ...} -> structured answer (Claude)
POST /context         -> {"question": ...} -> prompt for the on-device model
POST /chat-log        -> {"question","answer"} save an on-device exchange
POST /pause /resume   -> toggle capture
POST /delete-recent   -> delete last 10 minutes of captures
POST /memory/approve  -> {"line": ...} pending -> confirmed
POST /memory/delete   -> {"line": ...} remove pending line
POST /vault/reindex   -> re-scan the vault folder
POST /vault/delete    -> {"name": ...} delete a vault file
POST /vault/note      -> {"title","text"} create a markdown note in the vault
POST /killlist        -> {"apps": [...], "url_patterns": [...]} user additions
"""

import hmac
import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, db, digest, memory

log = logging.getLogger("rewisp")

PORT = 43117

# manual digest runs in a worker thread; UI polls /digest/status
_digest = {"running": False, "error": None}


def _engine_availability() -> dict:
    import shutil as _sh
    import urllib.request
    ollama = False
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1)
        ollama = True
    except OSError:
        pass
    return {"claude": bool(_sh.which("claude")),
            "codex": bool(_sh.which("codex")),
            "ollama": ollama}


def _today_utc_bounds() -> tuple[str, str]:
    now = datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    fmt = "%Y-%m-%d %H:%M:%S"
    return (start.astimezone(timezone.utc).strftime(fmt),
            (start + timedelta(days=1)).astimezone(timezone.utc).strftime(fmt))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        if not n or n > 1_000_000:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except json.JSONDecodeError:
            return {}

    def _authorized(self) -> bool:
        sent = self.headers.get("X-Rewisp-Token", "")
        return bool(sent) and hmac.compare_digest(sent, config.api_token())

    # -- GET -------------------------------------------------------------

    def do_GET(self):
        if not self._authorized():
            return self._json({"error": "unauthorized"}, 401)
        conn = db.connect()
        try:
            if self.path == "/status":
                since, until = _today_utc_bounds()
                n_today, = conn.execute(
                    "SELECT COUNT(*) FROM captures WHERE ts >= ? AND ts < ?",
                    (since, until)).fetchone()
                n_total, = conn.execute("SELECT COUNT(*) FROM captures").fetchone()
                from . import daemon, screen
                self._json({
                    "paused": config.PAUSE_FLAG.exists(),
                    "capture_state": daemon.STATE.get("capture", "unknown"),
                    "screen_permission": screen.has_screen_recording_permission(),
                    "captures_today": n_today,
                    "captures_total": n_total,
                    "db_mb": round(config.DB_PATH.stat().st_size / 1e6, 1)
                             if config.DB_PATH.exists() else 0,
                    "digest_calls_this_month": digest.calls_this_month(),
                })
            elif self.path == "/recap":
                today = datetime.now().astimezone().strftime("%Y-%m-%d")
                row = conn.execute("SELECT summary_md FROM summaries WHERE date=?",
                                   (today,)).fetchone()
                if row and row[0]:
                    self._json({"source": "digest", "recap": row[0]})
                else:
                    report = digest.compute_time_report(conn, datetime.now().astimezone())
                    since, until = _today_utc_bounds()
                    titles = [r[0] for r in conn.execute(
                        "SELECT DISTINCT COALESCE(NULLIF(window_title,''), app) FROM captures "
                        "WHERE ts >= ? AND ts < ? ORDER BY id DESC LIMIT 6",
                        (since, until))]
                    self._json({"source": "local", "time_report": report,
                                "recent_titles": titles})
            elif self.path == "/threads":
                row = conn.execute(
                    "SELECT date, threads_md FROM summaries ORDER BY date DESC LIMIT 1"
                ).fetchone()
                self._json({"date": row[0] if row else None,
                            "threads": row[1] if row else ""})
            elif self.path == "/memory":
                confirmed, pending = memory.read_sections()
                self._json({"confirmed": confirmed, "pending": pending})
            elif self.path == "/chats":
                rows = conn.execute(
                    "SELECT ts, role, content FROM chats ORDER BY id DESC LIMIT 100"
                ).fetchall()
                self._json({"chats": [
                    {"ts": r[0], "role": r[1], "content": r[2]} for r in reversed(rows)]})
            elif self.path == "/vault":
                files = []
                for p in sorted(config.VAULT_DIR.glob("*")):
                    if p.is_file() and not p.name.startswith("."):
                        st = p.stat()
                        files.append({"name": p.name, "size": st.st_size,
                                      "mtime": int(st.st_mtime)})
                self._json({"files": files, "path": str(config.VAULT_DIR)})
            elif self.path == "/settings":
                self._json({**config.load_settings(),
                            "available": _engine_availability()})
            elif self.path == "/form-context":
                # Served from the daemon's tick cache — by the time the panel
                # asks, the panel itself is key and a live AX query would see
                # the panel's own search field instead of the user's.
                import time as _time
                from . import daemon
                field = daemon.STATE.get("last_field")
                if field and _time.time() - field.get("ts", 0) < 8:
                    self._json({"field": {k: v for k, v in field.items() if k != "ts"}})
                else:
                    self._json({"field": None})
            elif self.path == "/digest/status":
                self._json({"running": _digest["running"],
                            "error": _digest["error"],
                            "last_run": digest.last_run_date()})
            elif self.path == "/report":
                from . import export
                self._json(export.weekly_report(conn))
            elif self.path == "/killlist":
                user = config.load_user_kill_list()
                self._json({
                    "default_apps": sorted(config.DEFAULT_KILL_APPS),
                    "default_url_patterns": sorted(config.DEFAULT_KILL_URL_PATTERNS),
                    "apps": sorted(user["apps"]),
                    "url_patterns": sorted(user["url_patterns"]),
                })
            else:
                self._json({"error": "not found"}, 404)
        finally:
            conn.close()

    # -- POST ------------------------------------------------------------

    def do_POST(self):
        if not self._authorized():
            return self._json({"error": "unauthorized"}, 401)
        body = self._body()
        conn = db.connect()
        try:
            if self.path == "/ask":
                question = (body.get("question") or "").strip()
                if not question:
                    return self._json({"error": "empty question"}, 400)
                from . import ask
                try:
                    answer, meta = ask.ask(question)
                    self._json({"answer": answer,
                                "detail": meta.get("detail"),
                                "source": meta.get("source"),
                                "time": meta.get("time"),
                                "copy_text": meta.get("copy_text"),
                                "model": meta.get("model", "Claude")})
                except RuntimeError as e:
                    self._json({"error": str(e)}, 502)
            elif self.path == "/context":
                question = (body.get("question") or "").strip()
                if not question:
                    return self._json({"error": "empty question"}, 400)
                from . import ask
                prompt, meta = ask.build_prompt(question, compact=bool(body.get("compact", True)))
                self._json({"prompt": prompt, "n_captures": meta.get("n_captures", 0),
                            "fact": meta.get("fact")})
            elif self.path == "/chat-log":
                q = (body.get("question") or "").strip()
                a = (body.get("answer") or "").strip()
                if q and a:
                    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    conn.execute("INSERT INTO chats (ts, role, content) VALUES (?, 'user', ?)", (ts, q))
                    conn.execute("INSERT INTO chats (ts, role, content) VALUES (?, 'assistant', ?)", (ts, a))
                    conn.commit()
                self._json({"ok": True})
            elif self.path == "/pause":
                config.ensure_dirs()
                config.PAUSE_FLAG.touch()
                self._json({"paused": True})
            elif self.path == "/resume":
                config.PAUSE_FLAG.unlink(missing_ok=True)
                self._json({"paused": False})
            elif self.path == "/delete-recent":
                cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)
                          ).strftime("%Y-%m-%d %H:%M:%S")
                n = conn.execute("DELETE FROM captures WHERE ts >= ?", (cutoff,)).rowcount
                conn.commit()
                log.info("deleted last-10-min captures: %d rows", n)
                self._json({"deleted": n})
            elif self.path == "/memory/approve":
                self._memory_move(body.get("line", ""), approve=True)
            elif self.path == "/memory/delete":
                self._memory_move(body.get("line", ""), approve=False)
            elif self.path == "/settings":
                self._json(config.save_settings(body))
            elif self.path == "/digest":
                if _digest["running"]:
                    return self._json({"started": False, "error": "already running"}, 409)
                _digest.update(running=True, error=None)

                def _work():
                    try:
                        digest.run(force=bool(body.get("force", True)))
                    except Exception as e:  # noqa: BLE001
                        _digest["error"] = str(e)
                        log.exception("manual digest failed")
                    finally:
                        _digest["running"] = False

                threading.Thread(target=_work, name="rewisp-digest", daemon=True).start()
                self._json({"started": True})
            elif self.path == "/export":
                from . import export
                self._json(export.run(conn))
            elif self.path == "/vault/reindex":
                from . import vault
                res = vault.reindex(conn)
                res["refused"] = [{"name": n, "reason": r} for n, r in res["refused"]]
                self._json(res)
            elif self.path == "/vault/delete":
                name = body.get("name", "")
                target = (config.VAULT_DIR / name).resolve()
                # Path-traversal guard: must stay a direct child of the vault.
                if (not name or "/" in name or name.startswith(".")
                        or target.parent != config.VAULT_DIR.resolve()
                        or not target.is_file()):
                    return self._json({"error": "bad name"}, 400)
                target.unlink()
                from . import vault
                vault.reindex(conn)
                self._json({"deleted": name})
            elif self.path == "/vault/note":
                title = (body.get("title") or "note").strip()
                text = (body.get("text") or "").strip()
                if not text:
                    return self._json({"error": "empty note"}, 400)
                safe = "".join(c for c in title if c.isalnum() or c in " -_")[:60].strip() or "note"
                path = config.VAULT_DIR / f"{safe}.md"
                i = 2
                while path.exists():
                    path = config.VAULT_DIR / f"{safe}-{i}.md"
                    i += 1
                path.write_text(f"# {title}\n\n{text}\n")
                from . import vault
                res = vault.reindex(conn)
                refused = {n: r for n, r in res["refused"]}
                if path.name in refused:
                    # credential detection refused the note — delete and report
                    path.unlink(missing_ok=True)
                    return self._json({"error": f"refused: looks like it contains a "
                                                f"{refused[path.name]} — Rewisp never "
                                                f"stores credentials"}, 400)
                self._json({"created": path.name})
            elif self.path == "/killlist":
                apps = body.get("apps")
                pats = body.get("url_patterns")
                if not isinstance(apps, list) or not isinstance(pats, list):
                    return self._json({"error": "apps and url_patterns lists required"}, 400)
                config.save_user_kill_list([str(a) for a in apps], [str(p) for p in pats])
                self._json({"ok": True})
            else:
                self._json({"error": "not found"}, 404)
        finally:
            conn.close()

    def _memory_move(self, line: str, approve: bool):
        confirmed, pending = memory.read_sections()
        if line not in pending:
            return self._json({"error": "line not in pending"}, 404)
        pending.remove(line)
        if approve:
            confirmed.append(line)
        text = "# Rewisp memory\n\n## Confirmed\n"
        text += "".join(f"- {c}\n" for c in confirmed)
        text += "\n## Pending (approve or delete)\n"
        text += "".join(f"- {p}\n" for p in pending)
        config.MEMORY_PATH.write_text(text)
        self._json({"confirmed": confirmed, "pending": pending})


def start() -> ThreadingHTTPServer:
    config.api_token()  # ensure the token file exists before the UI reads it
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, name="rewisp-http", daemon=True).start()
    log.info("http api on 127.0.0.1:%d", PORT)
    return server
