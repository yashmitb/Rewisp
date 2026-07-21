"""Screen capture (in-memory CGImage, never written to disk), OCR via Vision, dedupe thumbnails."""

import os

import Quartz
import Vision
from AppKit import NSRunningApplication

from . import config


def _clean_app_name(name) -> str:
    """Strip invisible Unicode formatting chars (LRM/RLM/BOM/zero-width) from
    an app name before it's used anywhere, especially kill-list matching.

    Found live 2026-07-09: macOS reports WhatsApp's window owner name as
    '\\u200eWhatsApp' (leading LEFT-TO-RIGHT MARK). The kill list does an
    exact string match against "WhatsApp", so the invisible prefix made every
    check silently miss — 56 WhatsApp screens were captured and OCR'd despite
    WhatsApp being in the default kill list from day one. Never trust a raw
    OS-provided app name for a privacy-critical comparison again."""
    if not name:
        return ""
    return "".join(c for c in str(name)
                   if not (0x200B <= ord(c) <= 0x200F or c == "﻿"))


def frontmost_app() -> tuple[str, int]:
    """(app name, pid) of the frontmost application, via the window server.

    NSWorkspace.frontmostApplication() caches its first answer in a process
    without a running NSRunLoop (verified 2026-07-08), so we ask the window
    server for the frontmost layer-0 window's owner instead — always fresh.
    """
    wins = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    for w in wins or []:
        if w.get("kCGWindowLayer", 1) == 0:
            pid = int(w.get("kCGWindowOwnerPID", -1))
            name = w.get("kCGWindowOwnerName")
            if not name and pid > 0:
                app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
                name = app.localizedName() if app else None
            return (_clean_app_name(name), pid)
    return "", -1


def frontmost_info() -> tuple[str, int, str | None]:
    """(app name, pid, window title) in ONE window-server query — the tick
    loop runs at 0.5s, and app + title were two separate full window-list
    copies before."""
    wins = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    for w in wins or []:
        if w.get("kCGWindowLayer", 1) == 0:
            pid = int(w.get("kCGWindowOwnerPID", -1))
            name = w.get("kCGWindowOwnerName")
            if not name and pid > 0:
                app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
                name = app.localizedName() if app else None
            title = w.get("kCGWindowName")
            return (_clean_app_name(name), pid, str(title) if title else None)
    return "", -1, None


def frontmost_window_title(pid: int) -> str | None:
    """Title of the frontmost window owned by pid, via the window server (no AX needed)."""
    wins = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    for w in wins or []:
        if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowLayer", 1) == 0:
            name = w.get("kCGWindowName")
            return str(name) if name else None
    return None


def _display_for_pid(pid: int) -> int:
    """Display ID containing the frontmost window of pid; falls back to main display."""
    wins = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    bounds = None
    for w in wins or []:
        if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowLayer", 1) == 0:
            bounds = w.get("kCGWindowBounds")
            break
    if bounds:
        cx = bounds["X"] + bounds["Width"] / 2
        cy = bounds["Y"] + bounds["Height"] / 2
        err, displays, count = Quartz.CGGetActiveDisplayList(16, None, None)
        if err == 0:
            for d in displays[:count]:
                r = Quartz.CGDisplayBounds(d)
                if (r.origin.x <= cx < r.origin.x + r.size.width
                        and r.origin.y <= cy < r.origin.y + r.size.height):
                    return d
    return Quartz.CGMainDisplayID()


def capture_frontmost_display(pid: int):
    """CGImage of the display containing pid's frontmost window. In memory only."""
    return Quartz.CGDisplayCreateImage(_display_for_pid(pid))


def screen_locked_or_asleep() -> bool:
    d = Quartz.CGSessionCopyCurrentDictionary()
    if d is None:
        return True
    if d.get("CGSSessionScreenIsLocked", 0):
        return True
    return bool(Quartz.CGDisplayIsAsleep(Quartz.CGMainDisplayID()))


def seconds_since_any_input() -> float:
    return Quartz.CGEventSourceSecondsSinceLastEventType(
        Quartz.kCGEventSourceStateCombinedSessionState, Quartz.kCGAnyInputEventType)


def seconds_since_scroll() -> float:
    return Quartz.CGEventSourceSecondsSinceLastEventType(
        Quartz.kCGEventSourceStateCombinedSessionState, Quartz.kCGEventScrollWheel)


# --- dedupe -----------------------------------------------------------------

def thumbnail_gray(cg_image) -> bytes:
    """NxN 8-bit grayscale thumbnail of a CGImage, as raw bytes."""
    n = config.DEDUPE_THUMB_SIZE
    cs = Quartz.CGColorSpaceCreateDeviceGray()
    ctx = Quartz.CGBitmapContextCreate(None, n, n, 8, n, cs, Quartz.kCGImageAlphaNone)
    Quartz.CGContextSetInterpolationQuality(ctx, Quartz.kCGInterpolationLow)
    Quartz.CGContextDrawImage(ctx, Quartz.CGRectMake(0, 0, n, n), cg_image)
    data = Quartz.CGBitmapContextGetData(ctx)  # objc.varlist, not a ctypes pointer
    return bytes(data.as_buffer(n * n))


def is_duplicate(thumb: bytes, prev_thumb: bytes | None) -> bool:
    """True if fewer than DEDUPE_CHANGED_FRACTION of pixels changed vs previous thumbnail."""
    if prev_thumb is None or len(thumb) != len(prev_thumb):
        return False
    changed = sum(1 for a, b in zip(thumb, prev_thumb)
                  if abs(a - b) > config.DEDUPE_PIXEL_DELTA)
    return changed / len(thumb) < config.DEDUPE_CHANGED_FRACTION


# --- OCR --------------------------------------------------------------------

def _ocr_boxes(cg_image) -> list[tuple[float, float, str]]:
    """Vision text boxes for one image: [(mid_y, x, text)], normalized 0-1,
    origin bottom-left (Vision's convention). Accurate mode, latest revision."""
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)
    if hasattr(Vision, "VNRecognizeTextRequestRevision3"):
        request.setRevision_(Vision.VNRecognizeTextRequestRevision3)
    if request.respondsToSelector_("setAutomaticallyDetectsLanguage:"):
        request.setAutomaticallyDetectsLanguage_(True)
    ok, err = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"Vision OCR failed: {err}")
    boxes = []
    for obs in request.results() or []:
        top = obs.topCandidates_(1)
        if top and top.count() > 0:
            bb = obs.boundingBox()
            mid_y = bb.origin.y + bb.size.height / 2
            boxes.append((mid_y, bb.origin.x, str(top.objectAtIndex_(0).string())))
    return boxes


def _tile_boxes(cg_image, width: int, height: int) -> list[tuple[float, float, str]]:
    """Second pass: OCR 2x2 overlapping tiles at full resolution. Vision's
    effective input is capped, so tiny text on a large frame is under-resolved
    in the whole-frame pass; per-quadrant it is ~2x larger and gets recognized.
    Tile coordinates are remapped into full-frame normalized space."""
    ov = config.OCR_TILE_OVERLAP
    tw, th = width * (0.5 + ov), height * (0.5 + ov)
    out = []
    for col in (0, 1):
        for row in (0, 1):
            # CGImage crop rect: pixel space, origin top-left
            x0 = min(col * width * (0.5 - ov), width - tw)
            y0 = min(row * height * (0.5 - ov), height - th)
            tile = Quartz.CGImageCreateWithImageInRect(
                cg_image, Quartz.CGRectMake(x0, y0, tw, th))
            if tile is None:
                continue
            for mid_y, x, text in _ocr_boxes(tile):
                gx = (x0 + x * tw) / width
                # tile mid_y is bottom-left normalized within the tile; the
                # tile's top edge sits y0 pixels below the frame's top edge
                gy = 1.0 - (y0 + (1.0 - mid_y) * th) / height
                out.append((gy, gx, text))
    return out


def _merge_boxes(primary: list, extra: list) -> list:
    """Add boxes from the tiled pass that the whole-frame pass missed.
    'Same box' = same normalized text within a small spatial distance
    (tiles overlap each other and the whole pass, so duplicates abound)."""
    def norm(t: str) -> str:
        return " ".join(t.split()).lower()

    seen: dict[str, list[tuple[float, float]]] = {}
    merged = list(primary)
    by_row: list[tuple[float, str]] = []  # (mid_y, norm text) for fragment check
    for mid_y, x, text in primary:
        seen.setdefault(norm(text), []).append((mid_y, x))
        by_row.append((mid_y, norm(text)))
    for mid_y, x, text in extra:
        key = norm(text)
        if len(key) < 2:
            continue  # stray glyphs from icons/tab strips — noise
        if any(abs(mid_y - py) < 0.02 and abs(x - px) < 0.03
               for py, px in seen.get(key, [])):
            continue
        # Fragment cut at a tile seam: a longer line on the same visual row
        # already starts with / contains this text — the whole pass saw the
        # full line, the tile saw it truncated (last word may be garbled).
        if len(key) >= 4 and any(
                abs(mid_y - py) < 0.015 and len(full) > len(key)
                and (key in full or key[:10] == full[:10])
                for py, full in by_row):
            continue
        # The reverse of the case above: the TILE read a longer span that
        # swallows a box the whole-frame pass already produced ("Finder" from the
        # whole pass, "Finder File" from the tile). Neither is a duplicate of the
        # other by text, so both used to survive and the row rendered as
        # "Finder  Finder File". Measured on live data: 59% of captures carried
        # doubling like this. Keep the longer read and drop the shorter, since
        # the tile sees small text at full resolution.
        superseded = [
            i for i, (my2, x2, t2) in enumerate(merged)
            if abs(mid_y - my2) < 0.015
            and len(norm(t2)) >= 3
            and norm(t2) != key
            and norm(t2) in key
        ]
        for i in reversed(superseded):
            merged.pop(i)

        seen.setdefault(key, []).append((mid_y, x))
        by_row.append((mid_y, key))
        merged.append((mid_y, x, text))
    return merged


def ocr_cgimage(cg_image) -> str:
    """OCR a CGImage with Apple Vision. Local, free.

    Recall strategy: whole-frame pass + (for large frames) a 2x2 overlapping
    tile pass merged in — catches small text the whole pass under-resolves.
    Vision returns observations in detection order, which on dense multi-column
    pages (Canvas, docs) is scrambled. Reassemble reading order: group boxes
    into visual rows by y, sort rows top-to-bottom and boxes left-to-right.
    """
    boxes = _ocr_boxes(cg_image)
    width = Quartz.CGImageGetWidth(cg_image)
    height = Quartz.CGImageGetHeight(cg_image)
    if config.OCR_TILING and width >= config.OCR_TILE_MIN_WIDTH:
        boxes = _merge_boxes(boxes, _tile_boxes(cg_image, width, height))
    if not boxes:
        return ""

    # Drop the macOS menu bar. Every capture on every Mac begins with it —
    # measured at 100% of 500 live captures — and it is never content: the app
    # name, its menus, the clock, the battery. Storing it costs space in the
    # database, room in the prompt, and precision in search, where "File Edit
    # View Window Help" matches everything and distinguishes nothing.
    #
    # Vision's y origin is bottom-left, so the bar sits at the TOP of the range.
    # The threshold is generous enough for the notch and tall menu bars, and
    # applies only to the thin strip: a box that merely starts up there but
    # extends down is real content and stays.
    # Computed from the frame, not a constant: the bar is a fixed ~24 logical
    # points, so its share of the screen depends on the display. A hardcoded
    # fraction is right on one Mac and wrong on the next.
    menubar_pt = config.OCR_MENUBAR_POINTS
    logical_h = max(height / 2, 1)          # Retina frames are 2x
    cutoff = 1.0 - (menubar_pt / logical_h)
    boxes = [b for b in boxes if b[0] < cutoff]

    boxes.sort(key=lambda b: -b[0])  # top of screen first
    ROW_TOLERANCE = 0.012  # ~1% of screen height counts as the same visual row
    rows: list[list[tuple[float, str]]] = []
    row_y = None
    for mid_y, x, text in boxes:
        if row_y is None or row_y - mid_y > ROW_TOLERANCE:
            rows.append([])
            row_y = mid_y
        rows[-1].append((x, text))
    lines = ["  ".join(t for _, t in sorted(row, key=lambda b: b[0])) for row in rows]
    return "\n".join(lines)


def has_screen_recording_permission() -> bool:
    """Can THIS process actually capture right now?

    CGPreflightScreenCaptureAccess caches its answer for the lifetime of the
    process, which is correct here: macOS only lets a process capture if it had
    the grant when it started. Flipping the switch in System Settings does not
    retroactively empower a running process — it has to be restarted.
    """
    return bool(Quartz.CGPreflightScreenCaptureAccess())


def screen_recording_granted_live() -> bool:
    """Is the toggle switched on *right now*, regardless of this process's cache?

    Needed because the cached preflight above can never flip to True inside a
    running daemon, so anything waiting on it waits forever — the daemon reported
    "permission not granted" indefinitely after the user had granted it.

    Window titles are the tell: macOS redacts kCGWindowName for every process
    that lacks Screen Recording, and un-redacts it the moment the grant lands.
    This reads current state with no caching.
    """
    try:
        wins = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID) or []
    except Exception:
        return False
    own = os.getpid()
    for w in wins:
        # Normal app windows only (layer 0); menu bars and shadows are noise.
        if w.get("kCGWindowLayer", 1) != 0:
            continue
        if w.get("kCGWindowOwnerPID") == own:
            continue          # our own titles are always visible to us
        if w.get("kCGWindowName"):
            return True
    return False


def permission_state() -> tuple[bool, bool]:
    """(usable_now, granted_but_needs_restart)."""
    usable = has_screen_recording_permission()
    if usable:
        return True, False
    return False, screen_recording_granted_live()


def request_screen_recording_permission() -> bool:
    return bool(Quartz.CGRequestScreenCaptureAccess())
