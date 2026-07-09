"""Vault: user-dropped files about himself (~/Rewisp/vault/). Text extracted on ingest,
indexed into its own FTS table. Vault is trusted truth — beats screen data on conflict.
Refuses files that look like they contain credentials."""

import logging
import re
import subprocess
from pathlib import Path

from . import config, db

log = logging.getLogger("rewisp")

VAULT_SCHEMA = """
CREATE TABLE IF NOT EXISTS vault_files (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE,
  mtime REAL,
  content TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS vault_fts USING fts5(
  content, path, content=vault_files, content_rowid=id
);
CREATE TRIGGER IF NOT EXISTS vault_ai AFTER INSERT ON vault_files BEGIN
  INSERT INTO vault_fts(rowid, content, path) VALUES (new.id, new.content, new.path);
END;
CREATE TRIGGER IF NOT EXISTS vault_ad AFTER DELETE ON vault_files BEGIN
  INSERT INTO vault_fts(vault_fts, rowid, content, path)
  VALUES ('delete', old.id, old.content, old.path);
END;
"""

# Never store credentials. Heuristics, deliberately over-cautious.
CREDENTIAL_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "SSN-like number"),
    (re.compile(r"\b(?:\d[ -]?){15,16}\b"), "card-like number"),
    (re.compile(r"(?i)\bpassword\s*[:=]\s*\S+"), "password assignment"),
    (re.compile(r"(?i)\bapi[_ -]?key\s*[:=]\s*\S+"), "API key"),
]


def extract_text(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in (".md", ".txt"):
        return path.read_text(errors="replace")
    if suffix == ".docx":
        out = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(path)],
                             capture_output=True, text=True, timeout=30)
        return out.stdout if out.returncode == 0 else None
    if suffix == ".pdf":
        import Quartz
        from Foundation import NSURL
        pdf = Quartz.PDFDocument.alloc().initWithURL_(NSURL.fileURLWithPath_(str(path)))
        if pdf is None:
            return None
        return "\n".join(
            str(pdf.pageAtIndex_(i).string() or "") for i in range(pdf.pageCount()))
    return None  # unsupported type, skipped


def credential_check(text: str) -> str | None:
    for pattern, label in CREDENTIAL_PATTERNS:
        if pattern.search(text):
            return label
    return None


def reindex(conn=None) -> dict:
    """Sync vault folder into the index. Returns counts + refused files."""
    conn = conn or db.connect()
    conn.executescript(VAULT_SCHEMA)
    config.ensure_dirs()
    seen, added, refused = set(), 0, []
    for path in sorted(config.VAULT_DIR.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        rel = str(path.relative_to(config.VAULT_DIR))
        seen.add(rel)
        mtime = path.stat().st_mtime
        row = conn.execute("SELECT mtime FROM vault_files WHERE path=?", (rel,)).fetchone()
        if row and row[0] == mtime:
            continue
        text = extract_text(path)
        if text is None:
            continue
        reason = credential_check(text)
        if reason:
            refused.append((rel, reason))
            log.warning("vault: REFUSED %s (%s) — remove the credential and reindex", rel, reason)
            continue
        conn.execute("DELETE FROM vault_files WHERE path=?", (rel,))
        conn.execute("INSERT INTO vault_files (path, mtime, content) VALUES (?, ?, ?)",
                     (rel, mtime, text))
        added += 1
    # drop rows for deleted files
    removed = 0
    for (path,) in conn.execute("SELECT path FROM vault_files").fetchall():
        if path not in seen:
            conn.execute("DELETE FROM vault_files WHERE path=?", (path,))
            removed += 1
    conn.commit()
    return {"indexed": added, "removed": removed, "refused": refused}


def search(conn, query: str, limit: int = 5) -> list[dict]:
    conn.executescript(VAULT_SCHEMA)
    rows = conn.execute(
        """SELECT v.path, snippet(vault_fts, 0, '[', ']', ' … ', 40)
           FROM vault_fts JOIN vault_files v ON v.id = vault_fts.rowid
           WHERE vault_fts MATCH ? ORDER BY rank LIMIT ?""", (query, limit)).fetchall()
    return [{"path": p, "snippet": s} for p, s in rows]
