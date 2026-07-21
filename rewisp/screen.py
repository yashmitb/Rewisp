"""Screen capture (in-memory CGImage, never written to disk), OCR via Vision, dedupe thumbnails."""

import json
import os
import subprocess
from pathlib import Path

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

_ocr_helper_cache: str | None | bool = False  # False = not yet resolved


def _locate_ocr_helper() -> str | None:
    """Path to the bundled Swift OCR helper (Resources/rewisp-ocr), or None.

    Resolved once and cached: the daemon calls OCR on every capture and the
    binary's location never changes within a run.
    """
    global _ocr_helper_cache
    if _ocr_helper_cache is not False:
        return _ocr_helper_cache  # type: ignore[return-value]
    found: str | None = None
    if config.OCR_HELPER_BIN and os.path.exists(config.OCR_HELPER_BIN):
        found = config.OCR_HELPER_BIN
    else:
        here = Path(__file__).resolve()
        # Bundled: .../Contents/Resources/daemon/rewisp/screen.py
        #                       parents[2] = Resources
        # Dev repo: .../Rewisp/rewisp/screen.py -> parents[1] = repo root
        for cand in (here.parents[2] / "rewisp-ocr",
                     here.parents[1] / "ui" / "Rewisp.app" / "Contents"
                     / "Resources" / "rewisp-ocr"):
            if cand.exists():
                found = str(cand)
                break
    _ocr_helper_cache = found
    return found


def _cgimage_to_png(cg_image) -> bytes | None:
    """Encode a CGImage to PNG bytes in memory. Nothing touches disk — the bytes
    are piped to the OCR helper over stdin."""
    data = Quartz.CFDataCreateMutable(None, 0)
    dest = Quartz.CGImageDestinationCreateWithData(data, "public.png", 1, None)
    if dest is None:
        return None
    Quartz.CGImageDestinationAddImage(dest, cg_image, None)
    if not Quartz.CGImageDestinationFinalize(dest):
        return None
    return bytes(data)


def _document_boxes_swift(cg_image) -> list[tuple[float, float, str]] | None:
    """Text boxes from macOS 26's document recogniser via the bundled Swift
    helper, or None if unavailable/failed.

    The recogniser (RecognizeDocumentsRequest) is Swift-only and does not bridge
    to pyobjc, so it runs in a separate signed binary: we PNG-encode the frame in
    memory, pipe it in, and read back line-level boxes as JSON. Line granularity
    avoids the word/line/paragraph doubling the old flat pyobjc `blocks` array
    gave (130 doubled pairs vs 6), and the boxes are normalized bottom-left —
    identical to _ocr_boxes — so the menu-bar cutoff and reading-order assembly in
    ocr_cgimage consume them unchanged.

    Every failure mode (no binary, pre-26 macOS, decode error, bad JSON) returns
    None so ocr_cgimage falls back to the tiled path — a capture is never lost.
    """
    helper = _locate_ocr_helper()
    if not helper:
        return None
    png = _cgimage_to_png(cg_image)
    if not png:
        return None
    try:
        proc = subprocess.run([helper], input=png, capture_output=True, timeout=15)
    except Exception:  # noqa: BLE001 — subprocess/timeout: fall back, never crash capture
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        rows = json.loads(proc.stdout)
        boxes = [(float(r["y"]), float(r["x"]), str(r["t"]))
                 for r in rows if r.get("t")]
    except Exception:  # noqa: BLE001 — malformed output: fall back
        return None
    return boxes or None


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


def _boxes_tiled(cg_image, width: int, height: int) -> list[tuple[float, float, str]]:
    """The established engine: whole-frame Vision pass + (for large frames) a 2x2
    overlapping tile pass merged in to catch small text the whole pass
    under-resolves."""
    boxes = _ocr_boxes(cg_image)
    if config.OCR_TILING and width >= config.OCR_TILE_MIN_WIDTH:
        boxes = _merge_boxes(boxes, _tile_boxes(cg_image, width, height))
    return boxes


def _assemble(boxes: list[tuple[float, float, str]], height: int) -> str:
    """Menu-bar cutoff + reading-order assembly. Shared by both engines so an A/B
    comparison differs only in recognition, not in post-processing.

    Vision returns observations in detection order, which on dense multi-column
    pages (Canvas, docs) is scrambled. Group boxes into visual rows by y, sort
    rows top-to-bottom and boxes left-to-right.
    """
    if not boxes:
        return ""
    # Drop the macOS menu bar. Every capture on every Mac begins with it —
    # measured at 100% of 500 live captures — and it is never content: the app
    # name, its menus, the clock, the battery. Storing it costs space in the
    # database, room in the prompt, and precision in search, where "File Edit
    # View Window Help" matches everything and distinguishes nothing.
    #
    # Vision's y origin is bottom-left, so the bar sits at the TOP of the range.
    # Computed from the frame, not a constant: the bar is a fixed ~24 logical
    # points, so its share of the screen depends on the display.
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
    return "\n".join("  ".join(t for _, t in sorted(row, key=lambda b: b[0]))
                     for row in rows)


def ocr_cgimage(cg_image, app: str | None = None) -> str:
    """OCR a CGImage with Apple Vision. Local, free.

    Uses the document recogniser (Swift helper) when OCR_USE_DOCUMENTS is set,
    otherwise the tiled engine; either falls back to the tiled path if it yields
    nothing. When OCR_SHADOW_AB is on, both engines run and their metrics are
    logged (no screen text is written) so the two can be compared on real
    captures before the default is switched — see _log_ocr_ab.
    """
    width = Quartz.CGImageGetWidth(cg_image)
    height = Quartz.CGImageGetHeight(cg_image)

    boxes = _document_boxes_swift(cg_image) if config.OCR_USE_DOCUMENTS else None
    if boxes is None:
        boxes = _boxes_tiled(cg_image, width, height)
    text = _assemble(boxes, height)

    if config.OCR_SHADOW_AB:
        try:
            _log_ocr_ab(cg_image, width, height, app)
        except Exception:  # noqa: BLE001 — measurement must never affect a capture
            pass
    return text


# --- shadow A/B measurement (opt-in, metrics only) --------------------------

def _count_doubled(text: str) -> int:
    """Adjacent repeated tokens within a line — the signature of the hierarchy
    doubling the flat pyobjc path produced ('IDE IDE', 'File File')."""
    n = 0
    for line in text.split("\n"):
        toks = line.split()
        n += sum(1 for i in range(1, len(toks)) if toks[i] == toks[i - 1])
    return n


def _token_overlap(a: str, b: str) -> float:
    """Jaccard of the two lowercased word SETS. A number, never the words — this
    is what keeps the A/B log free of screen text. ~1.0 means the engines read
    the same content; a low value flags a screen worth a closer look."""
    sa, sb = set(a.lower().split()), set(b.lower().split())
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / max(len(sa | sb), 1)


def _log_ocr_ab(cg_image, width: int, height: int, app: str | None) -> None:
    """Run BOTH engines on this frame and append a metrics-only record to
    ~/Rewisp/ocr_ab.jsonl. No screen text is written — only counts, timings and a
    token-overlap ratio — so the log carries the same trust as daemon.log, not the
    plaintext of the screen. Off unless OCR_SHADOW_AB is set."""
    import time

    t = time.perf_counter()
    tiled = _assemble(_boxes_tiled(cg_image, width, height), height)
    tiled_ms = round((time.perf_counter() - t) * 1000)

    t = time.perf_counter()
    sboxes = _document_boxes_swift(cg_image)
    swift = _assemble(sboxes, height) if sboxes is not None else ""
    swift_ms = round((time.perf_counter() - t) * 1000)

    rec = {
        "ts": int(time.time()),
        "app": app or "",
        "swift_ok": sboxes is not None,
        "tiled_chars": len(tiled),
        "swift_chars": len(swift),
        "tiled_lines": tiled.count("\n") + 1 if tiled else 0,
        "swift_lines": swift.count("\n") + 1 if swift else 0,
        "tiled_doubled": _count_doubled(tiled),
        "swift_doubled": _count_doubled(swift),
        "overlap": round(_token_overlap(tiled, swift), 3),
        "tiled_ms": tiled_ms,
        "swift_ms": swift_ms,
    }
    with open(config.OCR_AB_LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")


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
