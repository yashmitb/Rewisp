"""Focused form field detection via Accessibility (AX).

When the search panel is summoned it asks what field the user was typing in
(the panel is non-activating, so the field keeps focus). The UI offers to look
that field up in the Vault — copy-assist only: Rewisp never fills or submits
forms on its own (brief rule: fill, never submit; we stay one step safer).

Uses the same Accessibility permission the pause hotkey already needs.
"""

import logging

from ApplicationServices import (
    AXUIElementCopyAttributeValue,
    AXUIElementCreateSystemWide,
)

log = logging.getLogger("rewisp")

_FIELD_ROLES = {"AXTextField", "AXTextArea", "AXSearchField", "AXComboBox"}


def _attr(element, name: str):
    try:
        err, value = AXUIElementCopyAttributeValue(element, name, None)
        if err == 0 and value is not None:
            return value
    except Exception:  # noqa: BLE001 — AX is fussy; never break the caller
        pass
    return None


def focused_field() -> dict | None:
    """{'role', 'label', 'app'} for the currently focused text input, else None."""
    system = AXUIElementCreateSystemWide()
    focused = _attr(system, "AXFocusedUIElement")
    if focused is None:
        return None
    role = _attr(focused, "AXRole")
    if str(role) not in _FIELD_ROLES:
        return None
    label = None
    for name in ("AXPlaceholderValue", "AXTitle", "AXDescription", "AXLabel"):
        v = _attr(focused, name)
        if v and str(v).strip():
            label = str(v).strip()
            break
    if not label:
        # web forms often label via a related title element
        title_el = _attr(focused, "AXTitleUIElement")
        if title_el is not None:
            v = _attr(title_el, "AXValue") or _attr(title_el, "AXTitle")
            if v and str(v).strip():
                label = str(v).strip()
    app = None
    app_el = _attr(system, "AXFocusedApplication")
    if app_el is not None:
        v = _attr(app_el, "AXTitle")
        app = str(v) if v else None
    return {"role": str(role), "label": label, "app": app}
