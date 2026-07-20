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
    s = config.load_settings()
    c = s.get("custom_api") or {}
    from . import localmodel
    return {"claude": bool(_sh.which("claude")),
            "codex": bool(_sh.which("codex")),
            "gemini": bool((s.get("gemini_api_key") or "").strip()),
            "custom": bool(c.get("base_url") and c.get("api_key") and c.get("model")),
            "local": localmodel.active_model() is not None,
            "ollama": ollama}


def _form_pid(body: dict) -> int | None:
    """The target app for form ops: the panel's captured pid, else the daemon's
    cached frontmost (must be recent and not Rewisp itself)."""
    import time as _time
    from . import daemon
    if body.get("pid"):
        try:
            return int(body["pid"])
        except (TypeError, ValueError):
            pass
    fm = daemon.STATE.get("frontmost")
    if fm and _time.time() - fm.get("ts", 0) < 30 and fm.get("app") != "Rewisp":
        return fm.get("pid")
    return None


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
                # usable = this process can capture; pending = the user has
                # granted it but the daemon hasn't restarted into it yet. Reporting
                # only the cached preflight made the UI insist permission was
                # missing long after the user had granted it.
                usable, pending = screen.permission_state()
                self._json({
                    "paused": config.PAUSE_FLAG.exists(),
                    "capture_state": daemon.STATE.get("capture", "unknown"),
                    "screen_permission": usable,
                    "permission_pending": pending,
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
            elif self.path.split("?")[0] == "/form-context":
                # Served from the daemon's tick cache — by the time the panel
                # asks, the panel itself is key and a live AX query would see
                # the panel's own search field instead of the user's.
                import time as _time
                from . import daemon, form as form_mod
                field = daemon.STATE.get("last_field")
                out = {"field": None, "form": None}
                if field and _time.time() - field.get("ts", 0) < 8:
                    out["field"] = {k: v for k, v in field.items() if k != "ts"}
                # Walk the app the user was looking at. The panel passes ?pid= (the
                # app frontmost when ⌘⇧Space fired) — most reliable; else fall back
                # to the daemon's cached frontmost.
                import urllib.parse as _up
                q = _up.parse_qs(_up.urlparse(self.path).query)
                pid = int(q["pid"][0]) if q.get("pid") else None
                if pid is None:
                    fm = daemon.STATE.get("frontmost")
                    if fm and _time.time() - fm.get("ts", 0) < 10 and fm.get("app") != "Rewisp":
                        pid = fm.get("pid")
                _n = 0
                if pid:
                    found = form_mod.query(pid)   # runs in a crash-isolated subprocess
                    if found and found.get("fields"):
                        out["form"] = found
                        _n = len(found["fields"])
                log.info("form-context path=%r pid=%s fields=%s", self.path, pid, _n)
                self._json(out)
            elif self.path.split("?")[0] == "/delta":
                # Diff a page over time. No params -> the current page (latest
                # capture) vs its previous version. ?page_key= targets a page;
                # ?before= (ISO) diffs latest vs the version at/before that time.
                import urllib.parse as _up
                from . import delta as _delta
                q = _up.parse_qs(_up.urlparse(self.path).query)
                key = q["page_key"][0] if q.get("page_key") else db.latest_page_key(conn)
                before = q["before"][0] if q.get("before") else None
                after = q["after"][0] if q.get("after") else None
                if not key:
                    return self._json({"error": "no page"}, 404)
                old, new = db.versions_for_key(conn, key, before=before, after=after)
                if not new or not old:
                    return self._json({"page_key": key, "have_two_versions": False})
                d = _delta.diff_texts(old["ocr_text"], new["ocr_text"])
                self._json({"page_key": key, "have_two_versions": True,
                            "old_ts": old["ts"], "new_ts": new["ts"], **d})
            elif self.path == "/nudges":
                self._json({"nudges": db.pending_nudges(conn)})
            elif self.path == "/mcp-status":
                # Has an external agent connected over MCP, and when did it last query?
                import json as _json_mod
                from . import mcp as _mcp
                act = {}
                if _mcp.ACTIVITY_PATH.exists():
                    try:
                        act = _json_mod.loads(_mcp.ACTIVITY_PATH.read_text())
                    except (ValueError, OSError):
                        act = {}
                self._json({
                    "connected": bool(act.get("last_seen")),
                    "last_seen": act.get("last_seen"),
                    "last_tool": act.get("last_tool"),
                    "calls": act.get("calls", 0),
                    "client": act.get("client"),
                    "expose_vault": config.load_settings().get("mcp_expose_vault", False),
                    "cli_command": _mcp.cli_command(),
                    "json_block": _json_mod.dumps({"mcpServers": {"rewisp": _mcp.server_entry()}}, indent=2),
                    "desktop_installed": _mcp.desktop_installed(),
                    "clients": _mcp.client_setups(),
                })
            elif self.path == "/forgetting":
                # Your forgetting signature + what's about to fade + pinned facts.
                from . import forgetting
                pins = [{"question": q, "answer": a, "created_at": c} for q, a, c in
                        conn.execute("SELECT question, answer, created_at FROM pinned "
                                     "ORDER BY id DESC LIMIT 20")]
                self._json({"signature": forgetting.signature(conn),
                            "fading": forgetting.about_to_fade(conn, limit=3),
                            "pinned": pins})
            elif self.path == "/promises":
                self._json({
                    "pending": db.promises_by_status(conn, ("pending",)),
                    "active": db.promises_by_status(conn, ("confirmed",)),
                })
            elif self.path == "/series":
                from . import numbers
                self._json({"series": numbers.active_series(conn, limit=6)})
            elif self.path == "/precog":
                from . import precog
                self._json({"suggestions": precog.suggest(conn, limit=3)})
            elif self.path == "/memory-layers":
                raw = conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
                eps = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
                cons_days = conn.execute("SELECT COUNT(DISTINCT date) FROM episodes").fetchone()[0]
                reinforced = conn.execute(
                    "SELECT COUNT(*) FROM captures WHERE COALESCE(recall_count,0) > 0").fetchone()[0]
                self._json({"raw_wisps": raw, "episodes": eps,
                            "consolidated_days": cons_days, "reinforced": reinforced})
            elif self.path == "/digest/status":
                self._json({"running": _digest["running"],
                            "error": _digest["error"],
                            "last_run": digest.last_run_date()})
            elif self.path == "/report":
                from . import export
                self._json(export.weekly_report(conn))
            elif self.path == "/hardware":
                from . import hardware, localmodel
                rec = hardware.recommend(localmodel.MODELS)
                self._json({**rec, "models": localmodel.MODELS})
            elif self.path == "/local/status":
                from . import localmodel
                self._json({
                    "mlx_installed": localmodel.mlx_installed(),
                    "installed": localmodel.installed_models(),
                    "active": localmodel.active_model(),
                    "server_running": localmodel.server_running(),
                    "download": localmodel.download_status(),
                    "models": localmodel.MODELS,
                })
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
            elif self.path == "/form-fill":
                # Resolve every field of the cached form against the Vault. Read-only
                # copy-assist: returns values, never writes into the page (that's a
                # separate, explicit action).
                from . import form
                pid = _form_pid(body)
                found = form.query(pid) if pid else None
                if not found or not found.get("fields"):
                    return self._json({"error": "no form detected"}, 404)
                labels = [f["label"] for f in found.get("fields", [])]
                resolved = form.resolve(conn, labels)
                self._json({"app": found.get("app"), "fields": resolved})
            elif self.path == "/form-write":
                # Write resolved Vault values into the page's fields. Fills only.
                from . import form
                pid = _form_pid(body)
                result = form.apply(pid) if pid else None   # crash-isolated subprocess
                self._json(result or {"error": "no form detected", "written": 0})
            elif self.path == "/chat-log":
                q = (body.get("question") or "").strip()
                a = (body.get("answer") or "").strip()
                if q and a:
                    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    conn.execute("INSERT INTO chats (ts, role, content) VALUES (?, 'user', ?)", (ts, q))
                    conn.execute("INSERT INTO chats (ts, role, content) VALUES (?, 'assistant', ?)", (ts, a))
                    conn.commit()
                    try:
                        from . import forgetting
                        forgetting.maybe_pin(conn, q, a)   # 3rd lookup -> pinned forever
                    except Exception:  # noqa: BLE001
                        pass
                self._json({"ok": True})
            elif self.path == "/request-permission":
                # Ask macOS to show its own Screen Recording prompt. It has to come
                # from the daemon: TCC prompts for the process that wants to
                # capture, and the UI app never captures anything. This is as close
                # to "grant it without leaving the window" as macOS allows —
                # there is no API to flip the switch programmatically.
                from . import screen
                usable, pending = screen.permission_state()
                if not usable and not pending:
                    screen.request_screen_recording_permission()
                self._json({"prompted": not usable and not pending,
                            "screen_permission": usable,
                            "permission_pending": pending})
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
                ids = [r[0] for r in conn.execute(
                    "SELECT id FROM captures WHERE ts >= ?", (cutoff,))]
                n = db.delete_captures(conn, ids)  # cascade choke point (fts + embedding)
                log.info("deleted last-10-min captures: %d rows", n)
                self._json({"deleted": n})
            elif self.path == "/precog/tapped":
                from . import precog
                precog.mark_tapped(conn, body.get("text", ""))
                self._json({"ok": True})
            elif self.path == "/dream/run":
                from . import dream
                if body.get("include_recent"):
                    days = [r[0] for r in conn.execute(
                        "SELECT DISTINCT date(ts) FROM captures ORDER BY date(ts)")]
                    total = sum(dream.consolidate_day(conn, d) for d in days)
                else:
                    total = dream.run_pending(conn)
                self._json({"ok": True, "episodes": total})
            elif self.path == "/promise/status":
                # confirm | done | dismissed
                db.set_promise_status(conn, int(body.get("id", 0)), body.get("status", "dismissed"))
                self._json({"ok": True})
            elif self.path == "/nudge/feedback":
                nid = int(body.get("id", 0))
                db.nudge_feedback(conn, nid, body.get("vote", ""))
                self._json({"ok": True})
            elif self.path == "/nudge/delivered":
                db.mark_nudge_delivered(conn, int(body.get("id", 0)))
                self._json({"ok": True})
            elif self.path == "/mcp/install-desktop":
                from . import mcp as _mcp
                self._json(_mcp.install_to_desktop())
            elif self.path == "/nudge/test":
                # Enqueue a demo nudge so the pill UI can be seen while nudges are
                # still disabled. Points at the most recent real wisp if there is one.
                row = conn.execute(
                    "SELECT id, app, substr(ocr_text,1,300) FROM captures ORDER BY id DESC LIMIT 1"
                ).fetchone()
                from . import dejavu as _dj
                src, appn, snip = (row if row else (None, "somewhere", "a page you visited"))
                clean = _dj.clean_snippet(snip) or "a page you visited"
                nid = db.enqueue_nudge(
                    conn, "dejavu", "You've seen something like this",
                    f"Test nudge — you saw this in {appn}: “{clean[:90]}”",
                    source_wisp_id=src, topic_key=f"test:{datetime.now().timestamp()}")
                self._json({"ok": True, "id": nid})
            elif self.path == "/memory/approve":
                self._memory_move(body.get("line", ""), approve=True)
            elif self.path == "/memory/delete":
                self._memory_move(body.get("line", ""), approve=False)
            elif self.path == "/memory/forget":
                ok = memory.forget(body.get("line", ""))
                confirmed, pending = memory.read_sections()
                self._json({"ok": ok, "confirmed": confirmed, "pending": pending})
            elif self.path == "/settings":
                self._json(config.save_settings(body))
            elif self.path == "/gemini-test":
                from . import ask
                ok, err = ask.gemini_selftest()
                self._json({"ok": ok, "error": err})
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
            elif self.path == "/local/download":
                from . import localmodel
                self._json(localmodel.download_async(body.get("model", "")))
            elif self.path == "/local/delete":
                from . import localmodel
                self._json(localmodel.delete_model(body.get("model", "")))
            elif self.path == "/local/stop":
                from . import localmodel
                localmodel.stop_server()
                self._json({"ok": True})
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
            elif self.path == "/browser-consent":
                # Onboarding: fire one AppleScript query at the chosen browser so
                # the macOS automation consent prompt happens now, not mid-use.
                from . import browser
                app = body.get("app", "")
                if not browser.is_browser(app):
                    return self._json({"error": "unknown browser"}, 400)
                url, title, _ = browser.active_tab(app)
                self._json({"ok": True, "responded": url is not None or title is not None})
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
