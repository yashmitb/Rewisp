"""Focused form field detection via Accessibility (AX).

When the search panel is summoned it asks what field the user was typing in
(the panel is non-activating, so the field keeps focus). The UI offers to look
that field up in the Vault — copy-assist only: Rewisp never fills or submits
forms on its own (brief rule: fill, never submit; we stay one step safer).

Uses the same Accessibility permission the pause hotkey already needs.
"""

import logging
import threading

from ApplicationServices import (
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
    AXUIElementCreateSystemWide,
    AXUIElementSetAttributeValue,
)

log = logging.getLogger("rewisp")

_FIELD_ROLES = {"AXTextField", "AXTextArea", "AXSearchField", "AXComboBox"}


def _locked(fn):
    """No-op now. AX entry points run on their caller's thread — the daemon tick
    (main thread) for prewarm/focused_field, and a dedicated subprocess for the
    deep walk (all_fields/write), so a crash can't take the daemon down."""
    return fn


# ---- crash isolation --------------------------------------------------------
# Any AX call against a Chromium browser can segfault — the deep tree walk AND even
# a single attribute set. So the daemon NEVER touches AX. Instead a persistent
# helper subprocess (rewisp.axhelper) owns all Accessibility: it stays alive to hold
# the browser's web-AX tree built (Chromium exposes it only while the enabling client
# lives), and if it segfaults the daemon just respawns it and stays up itself.

class _Helper:
    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()

    def _ensure(self):
        if self.proc and self.proc.poll() is None:
            return
        import os
        import subprocess
        import sys
        from pathlib import Path
        root = str(Path(__file__).resolve().parent.parent)
        env = dict(os.environ)
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "rewisp", "axhelper"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1, cwd=root, env=env)
        log.info("ax helper started (pid %s)", self.proc.pid)

    def send(self, cmd: dict) -> dict | None:
        import json
        with self.lock:
            try:
                self._ensure()
                self.proc.stdin.write(json.dumps(cmd) + "\n")
                self.proc.stdin.flush()
                line = self.proc.stdout.readline()
                if not line:                      # helper died (e.g. segfault)
                    log.warning("ax helper died; will respawn")
                    self.proc = None
                    return None
                return json.loads(line)
            except Exception as e:  # noqa: BLE001
                log.warning("ax helper error: %s", e)
                self.proc = None
                return None


_HELPER = _Helper()


def _clean(r: dict | None) -> dict | None:
    return r if r and not r.get("error") else None


def enable(pid: int) -> None:
    """Keep a browser's web-AX tree built (called from the daemon tick)."""
    _HELPER.send({"op": "enable", "pid": pid})


def query(pid: int) -> dict | None:
    """{'app','fields':[{label,filled}]} for the app's front window."""
    return _clean(_HELPER.send({"op": "fields", "pid": pid}))


def resolve_form(pid: int) -> dict | None:
    """{'app','fields':[{label,value,found}]} — fields resolved against the Vault."""
    return _clean(_HELPER.send({"op": "resolve", "pid": pid}))


def apply(pid: int) -> dict | None:
    """Fill the fields with Vault values. {'written', 'fields':[...]}."""
    return _clean(_HELPER.send({"op": "write", "pid": pid}))


def focused() -> dict | None:
    """The currently focused text field, via the helper (daemon never touches AX)."""
    return _clean(_HELPER.send({"op": "focused"}))


def helper_loop() -> None:
    """The axhelper subprocess: own all AX here. One JSON command per stdin line,
    one JSON result per stdout line. Long-lived so the browser AX tree stays built."""
    import json
    import sys

    from . import db
    conn = None
    while True:
        line = sys.stdin.readline()
        if not line:          # daemon closed the pipe -> exit
            break
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
            op = cmd.get("op")
            pid = int(cmd["pid"]) if cmd.get("pid") is not None else None
            if op == "focused":
                out = focused_field() or {}
            elif op == "enable":
                _enable_web_ax(AXUIElementCreateApplication(pid))
                out = {"ok": True}
            elif op == "fields":
                out = all_fields(pid) or {}
            elif op == "resolve":
                found = all_fields(pid) or {}
                labels = [f["label"] for f in found.get("fields", [])]
                if conn is None:
                    conn = db.connect()
                out = {"app": found.get("app"), "fields": resolve(conn, labels)}
            elif op == "write":
                if conn is None:
                    conn = db.connect()
                out = write(conn, pid) or {"written": 0, "fields": []}
            else:
                out = {"error": "unknown op"}
        except Exception as e:  # noqa: BLE001
            out = {"error": str(e)[:150]}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


def _attr(element, name: str):
    try:
        err, value = AXUIElementCopyAttributeValue(element, name, None)
        if err == 0 and value is not None:
            return value
    except Exception:  # noqa: BLE001 — AX is fussy; never break the caller
        pass
    return None


def _field_label(element) -> str | None:
    for name in ("AXPlaceholderValue", "AXTitle", "AXDescription", "AXLabel", "AXHelp"):
        v = _attr(element, name)
        if v and str(v).strip():
            return str(v).strip()
    # web forms often label via a related title element
    title_el = _attr(element, "AXTitleUIElement")
    if title_el is not None:
        v = _attr(title_el, "AXValue") or _attr(title_el, "AXTitle")
        if v and str(v).strip():
            return str(v).strip()
    return None


_LABEL_ROLES = {"AXStaticText", "AXText", "AXLabel", "AXHeading"}


def _label_from_siblings(siblings, index: int) -> str | None:
    """Web forms often render the label as a separate text node just before the
    input (e.g. 'First Name' above the box). Look back a few siblings for it."""
    if siblings is None:
        return None
    for j in range(index - 1, max(-1, index - 4), -1):
        c = siblings[j]
        role = _attr(c, "AXRole")
        if str(role) in _LABEL_ROLES:
            v = _attr(c, "AXValue") or _attr(c, "AXTitle")
            if v and str(v).strip() and len(str(v).strip()) < 60:
                return str(v).strip()
    return None


@_locked
def focused_field() -> dict | None:
    """{'role', 'label', 'app'} for the currently focused text input, else None."""
    system = AXUIElementCreateSystemWide()
    focused = _attr(system, "AXFocusedUIElement")
    if focused is None:
        return None
    role = _attr(focused, "AXRole")
    if str(role) not in _FIELD_ROLES:
        return None
    app = None
    app_el = _attr(system, "AXFocusedApplication")
    if app_el is not None:
        v = _attr(app_el, "AXTitle")
        app = str(v) if v else None
    return {"role": str(role), "label": _field_label(focused), "app": app}


def _enable_web_ax(app_el) -> None:
    """Chromium browsers (Dia, Chrome, Arc, Edge, Brave) only build their web-page
    accessibility tree once an AX client asks. Flip these on so the form fields
    inside a web page become visible to the walk. Harmless for native apps."""
    for attr in ("AXManualAccessibility", "AXEnhancedUserInterface"):
        try:
            AXUIElementSetAttributeValue(app_el, attr, True)
        except Exception:  # noqa: BLE001
            pass


@_locked
def prewarm(pid: int) -> None:
    """Enable a Chromium browser's web AX tree ahead of time (called while it's
    frontmost) so the first form lookup after ⌘⇧Space is instant, not empty."""
    try:
        _enable_web_ax(AXUIElementCreateApplication(pid))
    except Exception:  # noqa: BLE001
        pass


def _walk_fields(element, out: list, depth: int, budget: list,
                 siblings=None, index: int = 0) -> None:
    """Depth-first collect of editable text fields under `element`. Budget-capped so
    a huge web AX tree can't stall the daemon tick. Falls back to a neighboring text
    node for the label when the field exposes none itself."""
    if depth > 30 or budget[0] <= 0:
        return
    budget[0] -= 1
    role = str(_attr(element, "AXRole") or "")
    if role in _FIELD_ROLES:
        label = _field_label(element) or _label_from_siblings(siblings, index)
        if label and len(label) < 60:
            val = _attr(element, "AXValue")
            out.append({"label": label,
                        "filled": bool(val and str(val).strip())})
    children = _attr(element, "AXChildren") or []
    for i, child in enumerate(children):
        _walk_fields(child, out, depth + 1, budget, children, i)


@_locked
def all_fields(pid: int | None = None) -> dict | None:
    """Every editable text field in an app's front window: {'app', 'fields': [...]}.
    Pass the target app's pid (the search panel does this so it walks the app the
    user was looking at, not the panel). None if no window / no fields.
    Works whether or not a field is currently focused — just being on the form is enough."""
    if pid:
        app_el = AXUIElementCreateApplication(pid)
    else:
        system = AXUIElementCreateSystemWide()
        app_el = _attr(system, "AXFocusedApplication")
    if app_el is None:
        return None
    _enable_web_ax(app_el)
    win = _attr(app_el, "AXFocusedWindow") or _attr(app_el, "AXMainWindow")
    if win is None:
        wins = _attr(app_el, "AXWindows") or []
        win = wins[0] if wins else None
    if win is None:
        return None
    collected: list = []
    _walk_fields(win, collected, 0, [6000])
    if not collected:
        # Chromium builds its web AX tree lazily after the enable above — give it a
        # beat and walk once more so the first summon on a page still works.
        import time as _t
        _t.sleep(0.5)
        _walk_fields(win, collected, 0, [6000])
    seen: set = set()
    fields = []
    for f in collected:  # de-dupe by label, keep order
        key = f["label"].lower()
        if key not in seen:
            seen.add(key)
            fields.append(f)
    if not fields:
        return None
    app = _attr(app_el, "AXTitle")
    return {"app": str(app) if app else None, "fields": fields}


# Never auto-fill these — payment/credentials. Even if something in the Vault
# happens to match, we refuse (a wrong guess here is dangerous, e.g. a phone
# number landing in a card-number box).
_SENSITIVE = ("password", "passcode", "cvc", "cvv", "security code", "card number",
              "cardnumber", "card no", "credit card", "debit card number",
              "ssn", "social security", "routing number", "account number")


def _address_component(conn, which: str) -> str | None:
    """Pull city / state / zip / country / street out of the full Vault address,
    e.g. '1412 N Drago Way, Mountain House, California 95391, United States'."""
    import re

    from . import ask
    hit = ask.vault_fact(conn, "what is my address")
    full = (hit.get("copy_text") or hit.get("answer")) if hit else None
    if not full or "," not in full:
        return None
    parts = [p.strip() for p in full.split(",") if p.strip()]
    if len(parts) < 2:
        return None
    if which == "street":
        return parts[0]
    country = parts[-1] if len(parts) >= 3 and not re.search(r"\d", parts[-1]) else None
    if which == "country":
        return country
    # find the "State ZIP" chunk (has a 5-digit zip)
    state = zip_code = None
    for p in parts[1:]:
        m = re.search(r"\b(\d{5})(?:-\d{4})?\b", p)
        if m:
            zip_code = m.group(1)
            state = p.replace(m.group(0), "").strip() or None
    if which == "zip":
        return zip_code
    if which == "state":
        return state
    if which == "city":
        mids = parts[1:-1] if country else parts[1:]
        for p in mids:
            if not re.search(r"\d{5}", p):
                return p
    return None


def _resolve_one(conn, label: str) -> str | None:
    from . import ask
    low = label.lower()
    # Payment / credential fields: never fill.
    if any(k in low for k in _SENSITIVE):
        return None
    # Address components come from the one full address in the Vault.
    if "country" in low:
        c = _address_component(conn, "country")
        if c:
            return c
    elif any(k in low for k in ("city", "town")):
        c = _address_component(conn, "city")
        if c:
            return c
    elif any(k in low for k in ("state", "province")):
        c = _address_component(conn, "state")
        if c:
            return c
    elif any(k in low for k in ("zip", "postal", "postcode")):
        c = _address_component(conn, "zip")
        if c:
            return c
    elif "street" in low or "address line 1" in low:
        c = _address_component(conn, "street")
        if c:
            return c

    hit = ask.vault_fact(conn, f"what is my {label}?")
    value = (hit.get("copy_text") or hit.get("answer")) if hit else None
    # A "name" Vault entry answers both first- and last-name fields with the full
    # name; split it so each field gets the right part.
    if value and 2 <= len(value.split()) <= 4:
        if any(k in low for k in ("first name", "given name", "forename")):
            value = value.split()[0]
        elif any(k in low for k in ("last name", "surname", "family name")):
            value = value.split()[-1]
    return value


def resolve(conn, labels: list[str]) -> list[dict]:
    """Map each field label to the user's own value from the Vault.
    [{'label', 'value'|None, 'found'}]. Never touches credentials — Vault refuses those."""
    out = []
    for label in labels:
        v = _resolve_one(conn, label)
        out.append({"label": label, "value": v, "found": bool(v)})
    return out


def _collect_elements(element, out: list, depth: int, budget: list,
                      siblings=None, index: int = 0) -> None:
    """Like _walk_fields but keeps the AX element ref so we can write to it."""
    if depth > 30 or budget[0] <= 0:
        return
    budget[0] -= 1
    role = str(_attr(element, "AXRole") or "")
    if role in _FIELD_ROLES:
        label = _field_label(element) or _label_from_siblings(siblings, index)
        if label and len(label) < 60:
            out.append((element, label))
    children = _attr(element, "AXChildren") or []
    for i, child in enumerate(children):
        _collect_elements(child, out, depth + 1, budget, children, i)


@_locked
def write(conn, pid: int) -> dict:
    """Fill each form field on the page with the user's Vault value via AX.
    Fills only — never clicks buttons, never submits. {'written', 'fields': [...]}."""
    app_el = AXUIElementCreateApplication(pid)
    _enable_web_ax(app_el)
    win = _attr(app_el, "AXFocusedWindow") or _attr(app_el, "AXMainWindow")
    if win is None:
        wins = _attr(app_el, "AXWindows") or []
        win = wins[0] if wins else None
    if win is None:
        return {"written": 0, "fields": []}
    els: list = []
    _collect_elements(win, els, 0, [6000])
    if not els:
        import time as _t
        _t.sleep(0.5)
        _collect_elements(win, els, 0, [6000])
    results = []
    written = 0
    seen: set = set()
    for el, label in els:
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        value = _resolve_one(conn, label)
        ok = False
        if value:
            try:
                ok = AXUIElementSetAttributeValue(el, "AXValue", value) == 0
            except Exception:  # noqa: BLE001 — some fields refuse AXValue writes
                ok = False
        if ok:
            written += 1
        results.append({"label": label, "value": value, "written": ok})
    return {"written": written, "fields": results}
