"""End-to-end test of the persona endpoints over real HTTP.

Runs the actual server against a SANDBOX copy of the Vault on a spare port, so
every request goes through the same routing, auth, JSON handling and error paths
the app uses — and the live install, the live database and the real Vault are
never touched. Unit tests pass with a fixture; this is the thing that catches a
route that was never wired, a body key the handler doesn't read, or a 500 that
only happens through the socket.

    python3 scripts/persona_e2e.py
"""

import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

PORT = 43219                       # not the daemon's 43117
FAILED: list[str] = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{'  — ' + str(detail) if detail else ''}")
    if not cond:
        FAILED.append(name)


def main() -> int:
    sandbox = pathlib.Path(tempfile.mkdtemp(prefix="rewisp-e2e-"))
    real_vault = pathlib.Path.home() / "Rewisp" / "vault"

    from rewisp import config
    config.DATA_DIR = sandbox
    config.VAULT_DIR = sandbox / "vault"
    config.DB_PATH = sandbox / "rewisp.db"
    config.SETTINGS_PATH = sandbox / "settings.json"
    config.TOKEN_PATH = sandbox / ".api_token"
    config.VAULT_DIR.mkdir(parents=True)
    if real_vault.is_dir():                       # a realistic starting Vault
        for f in real_vault.iterdir():
            if f.is_file() and not f.name.startswith("."):
                shutil.copy(f, config.VAULT_DIR / f.name)
    print(f"  sandbox: {sandbox}")
    print(f"  copied {len(list(config.VAULT_DIR.iterdir()))} vault files\n")

    from rewisp import db, server, vault
    conn = db.connect()
    conn.executescript(vault.VAULT_SCHEMA)
    vault.reindex(conn)
    conn.close()

    server.PORT = PORT
    srv = server.start()
    time.sleep(0.6)
    tok = config.api_token()

    def call(method, path, body=None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"X-Rewisp-Token": tok, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    try:
        print("── auth ──")
        bad = urllib.request.Request(f"http://127.0.0.1:{PORT}/personas")
        try:
            urllib.request.urlopen(bad, timeout=10)
            check("unauthorized request is refused", False, "it was allowed")
        except urllib.error.HTTPError as e:
            check("unauthorized request is refused", e.code == 401, f"HTTP {e.code}")

        print("\n── discovery ──")
        s, d = call("GET", "/personas")
        check("GET /personas responds", s == 200, f"HTTP {s}")
        check("no personas exist on a fresh Vault", d.get("personas") == [], d.get("personas"))
        check("the four known personas are offered", len(d.get("known", [])) == 4)
        check("primary defaults to personal", d.get("primary") == "personal")

        print("\n── the proposal (nothing may move) ──")
        s, d = call("GET", "/personas/propose")
        check("GET /personas/propose responds", s == 200, f"HTTP {s}")
        lines = d.get("lines", [])
        check("the multi-identity note is found", len(lines) >= 1,
              [x["path"] for x in lines])
        before = sorted(p.name for p in config.VAULT_DIR.iterdir())
        s2, _ = call("GET", "/personas/propose")
        check("proposing twice changes nothing on disk",
              sorted(p.name for p in config.VAULT_DIR.iterdir()) == before)

        print("\n── applying a line split ──")
        target = lines[0]
        s, d = call("POST", "/personas/apply-line-split",
                    {"path": target["path"], "lines": target["lines"]})
        check("POST apply-line-split succeeds", s == 200 and "written" in d, d)
        check("each persona got its own file", len(d.get("written", [])) >= 2, d.get("written"))
        check("the original is recoverable",
              (config.VAULT_DIR / d.get("backup", "x")).is_file(), d.get("backup"))

        print("\n── answering, per persona ──")
        s, d = call("GET", "/personas?q=what%20is%20my%20email")
        vals = {v["label"]: v["answer"] for v in d.get("values", [])}
        check("more than one identity answers", len(vals) >= 2, list(vals))
        check("the school answer is the .edu", any(a.endswith(".edu") for a in vals.values()))
        check("the personal answer is not the .edu",
              any(not a.endswith(".edu") and "@" in a for a in vals.values()))
        s, d = call("GET", "/personas?q=what%20is%20my%20address")
        addrs = [v["answer"] for v in d.get("values", [])]
        check("an address question never answers with an email",
              all("@" not in a for a in addrs), addrs)

        print("\n── site memory (the safety rule) ──")
        s, d = call("GET", "/persona/for-site?url=https://example.com/signup")
        check("an unseen site is NOT settled", d.get("settled") is False and d.get("persona") is None, d)
        s, d = call("POST", "/persona/site", {"url": "https://example.com/x", "persona": "school"})
        check("a choice is accepted", s == 200 and d.get("ok"), d)
        s, d = call("GET", "/persona/for-site?url=https://example.com/other")
        check("it is remembered for the whole host", d.get("persona") == "school", d)
        s, d = call("POST", "/persona/site", {"url": "https://example.com/x", "persona": "work"})
        s, d = call("GET", "/persona/for-site?url=https://example.com/x")
        check("changing it overwrites", d.get("persona") == "work", d)
        s, d = call("POST", "/persona/site", {"url": "https://example.com/x", "forget": True})
        s, d = call("GET", "/persona/for-site?url=https://example.com/x")
        check("forgetting returns it to unsettled", d.get("settled") is False, d)

        print("\n── hostile input ──")
        s, d = call("POST", "/persona/site", {"url": "https://x.com", "persona": "../../etc"})
        check("a traversal persona name is refused outright", s == 400, f"HTTP {s} {d}")
        s2, d2 = call("GET", "/persona/for-site?url=https://x.com")
        check("and nothing was settled on it", d2.get("settled") is False, d2)
        # Against a file that really is there, so this cannot pass on "bad path".
        call("POST", "/vault/note", {"title": "traversal probe", "text": "hello"})
        s, d = call("POST", "/personas/apply-line-split",
                    {"path": "traversal probe.md",
                     "lines": [{"text": "hello", "persona": "../../etc"}]})
        check("a line cannot be filed under a persona that does not exist",
              s == 400 and "no such persona" in str(d), f"HTTP {s} {d}")
        s, d = call("POST", "/personas/apply-split",
                    {"moves": [{"path": "../../../etc/passwd", "persona": "work"}]})
        check("a path outside the Vault is refused", d.get("moved") == [], d)
        check("nothing escaped the Vault",
              all(p.resolve().parent == config.VAULT_DIR.resolve() or p.is_dir()
                  for p in config.VAULT_DIR.iterdir()))
        s, d = call("POST", "/personas/apply-line-split", {"path": "", "lines": []})
        check("a malformed split is a 400, not a 500", s == 400, f"HTTP {s}")
        s, d = call("POST", "/persona/site", {"url": "https://y.com"})
        check("a missing persona is a 400", s == 400, f"HTTP {s}")

        print("\n── folders, repeats, and odd input ──")
        s, d = call("POST", "/personas/folders", {"names": ["work", "../escape", "Rewisp", ""]})
        made = d.get("created", [])
        check("folders are created from clean names", "work" in made and "rewisp" in made, made)
        check("a traversal folder name never lands", not any("/" in m or ".." in m for m in made), made)
        check("every folder sits directly in the Vault",
              all((config.VAULT_DIR / m).resolve().parent == config.VAULT_DIR.resolve()
                  for m in made))

        # Splitting the same note again: the file is gone, so this must be a
        # clean refusal rather than a traceback through the socket.
        s, d = call("POST", "/personas/apply-line-split",
                    {"path": target["path"], "lines": target["lines"]})
        check("re-splitting an already-split note fails cleanly",
              s == 400 and "error" in d, f"HTTP {s} {d}")

        s, d = call("GET", "/personas?q=%27%3B%20DROP%20TABLE%20vault_files%3B--")
        check("an injection in the question is harmless", s == 200, f"HTTP {s}")
        s2, d2 = call("GET", "/personas")
        check("the vault index survived it", s2 == 200 and "personas" in d2)

        s, d = call("GET", "/personas?q=")
        check("an empty question returns no values", d.get("values") == [], d.get("values"))

        s, d = call("POST", "/persona/site",
                    {"app": "Mail", "persona": "work"})
        s, d = call("GET", "/persona/for-site?app=Mail")
        check("a native app can be settled too", d.get("persona") == "work", d)

        # The settings list forgets by the STORED KEY. Handing back a URL rebuilt
        # from it ("https://app::mail") parsed to the host "app", matched no row,
        # and left a native app permanently settled with a dead button.
        s, d = call("GET", "/personas")
        keys = [x["site"] for x in d.get("sites", [])]
        check("the app row is listed by its stored key", "app::mail" in keys, keys)
        s, d = call("POST", "/persona/site", {"site": "app::mail", "forget": True})
        check("forgetting by that key works", d.get("forgotten") is True, d)
        s, d = call("GET", "/persona/for-site?app=Mail")
        check("the app is unsettled again", d.get("settled") is False, d)

        s, d = call("GET", "/persona/for-site")
        check("no url and no app is simply unsettled", d.get("settled") is False, d)

        print("\n── documents survived ──")
        import subprocess
        pdfs = [p for p in config.VAULT_DIR.iterdir() if p.suffix.lower() == ".pdf"]
        ok = all("PDF document" in subprocess.run(
            ["file", "-b", str(p)], capture_output=True, text=True).stdout for p in pdfs)
        check(f"all {len(pdfs)} PDFs are still PDFs", ok)
    finally:
        srv.shutdown()
        shutil.rmtree(sandbox, ignore_errors=True)

    print()
    if FAILED:
        print(f"  {len(FAILED)} FAILED: {FAILED}")
        return 1
    print("  all persona endpoint checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
