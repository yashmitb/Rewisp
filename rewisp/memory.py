"""Learned memory: ~/Rewisp/memory.md with Confirmed and Pending sections.
Digest appends proposals to Pending only. User promotes/deletes. Never auto-confirm."""

import re

from . import config

TEMPLATE = """# Rewisp memory

## Confirmed

## Pending (approve or delete)
"""


def ensure_file() -> None:
    config.ensure_dirs()
    if not config.MEMORY_PATH.exists():
        config.MEMORY_PATH.write_text(TEMPLATE)


def read_sections() -> tuple[list[str], list[str]]:
    """(confirmed_lines, pending_lines) — bullet text without the leading '- '."""
    ensure_file()
    text = config.MEMORY_PATH.read_text()

    def bullets(section: str) -> list[str]:
        m = re.search(rf"## {section}.*?\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
        if not m:
            return []
        return [ln[2:].strip() for ln in m.group(1).splitlines() if ln.startswith("- ")]

    return bullets("Confirmed"), bullets(r"Pending \(approve or delete\)")


def confirmed_text() -> str:
    confirmed, _ = read_sections()
    return "\n".join(f"- {c}" for c in confirmed)


def _similar(a: str, b: str) -> bool:
    """Fuzzy near-duplicate check — the digest often re-proposes a fact it already
    learned, worded differently ('DS student at UCSD…' vs 'Data Science student at
    UC San Diego…'). Exact-match dedup let those pile up. Catch high text overlap
    or a strong word-set overlap."""
    import re
    from difflib import SequenceMatcher
    if SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.72:
        return True

    def words(s: str) -> set[str]:
        out = set()
        for w in re.findall(r"[a-z0-9/]+", s.lower()):
            if w in _STOP or len(w) < 2:
                continue
            out.add(w[:-1] if w.endswith("s") and len(w) > 3 else w)   # crude stem
        return out

    wa, wb = words(a), words(b)
    if len(wa) >= 3 and len(wb) >= 3:
        if len(wa & wb) / min(len(wa), len(wb)) > 0.7:   # one nearly a subset of the other
            return True
    return False


_STOP = {"the", "a", "an", "he", "she", "his", "her", "with", "and", "for", "of",
         "to", "in", "on", "at", "is", "was", "as", "per", "also"}


def add_pending(proposals: list[str]) -> int:
    """Append new proposals to Pending. Dedupes (fuzzily) against everything
    already in Confirmed or Pending, so re-worded repeats don't pile up."""
    ensure_file()
    confirmed, pending = read_sections()
    existing = confirmed + pending
    new = []
    for p in proposals:
        p = p.strip()
        if p and not any(_similar(p, e) for e in existing) and not any(_similar(p, n) for n in new):
            new.append(p)
    if not new:
        return 0
    text = config.MEMORY_PATH.read_text()
    if not text.endswith("\n"):
        text += "\n"
    text += "".join(f"- {p}\n" for p in new)
    config.MEMORY_PATH.write_text(text)
    return len(new)
