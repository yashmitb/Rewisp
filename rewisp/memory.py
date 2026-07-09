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


def add_pending(proposals: list[str]) -> int:
    """Append new proposals to Pending. Dedupes against everything already there."""
    ensure_file()
    confirmed, pending = read_sections()
    existing = {p.lower() for p in confirmed + pending}
    new = []
    for p in proposals:
        p = p.strip()
        if p and p.lower() not in existing:
            existing.add(p.lower())
            new.append(p)
    if not new:
        return 0
    text = config.MEMORY_PATH.read_text()
    if not text.endswith("\n"):
        text += "\n"
    text += "".join(f"- {p}\n" for p in new)
    config.MEMORY_PATH.write_text(text)
    return len(new)
