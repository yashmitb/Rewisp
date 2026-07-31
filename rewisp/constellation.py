"""Constellation — the day drawn as a map of meaning, not a list of times.

Every product in this category ships the same picture: a linear scrubber you drag
through. That answers "what was on screen at 3pm" and nothing else. It cannot
show you the *shape* of a day, because time is the only axis it has.

This lays the day out by MEANING instead. Each place you spent real time becomes
a node, positioned by the embedding Rewisp already computed for it, so related
work sits together and unrelated work drifts apart. Then time is drawn back on
top as a trace through that space. Three questions get answered by one picture:

  - what did I actually work on       -> the clusters
  - how did my attention move         -> the trace, and the thick edges
  - what kept pulling me away         -> the long jumps between distant clusters

Measured on real data before it was built: an ordinary day is ~976 captures
across 70 pages, but only **6 pages carry more than five minutes** and 17 carry
more than one. So the map is a 6-17 node picture, not a 976-node hairball — the
filtering is what makes it legible, and it has to happen here rather than in the
UI.

Deliberately NOT built on `episodes`: Dream splits a cluster on every page_key
change, which yields 40-157 "episodes" a day. Those are fragments, not sessions.

Fully local and free — numpy over stored embeddings, no model call, no cloud.
"""

import logging
import math
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from . import db

log = logging.getLogger("rewisp")

# A place has to hold you for a full minute to earn a dot. Below that it's a
# redirect, a tab you closed, a login bounce — noise that turns the map into
# static. On live data this is what takes 70 pages down to 17.
MIN_DWELL_SECONDS = 60
# Hard ceiling regardless of dwell. Past ~18 the labels collide and the whole
# point (reading it at a glance) is lost; the tail is always the least-used pages.
MAX_NODES = 18
# Same cap the time report uses: a gap longer than this means you walked away,
# so it must not be credited to whatever happened to be on screen.
DWELL_CAP_SECONDS = 300
# Cosine bar for "these two places are the same topic". Single-link chains, so a
# low bar collapses a whole day into one colour — at 0.50 a real day rendered as
# 16 violet dots and one cyan, which tells the eye nothing. 0.62 keeps genuine
# groups together while actually separating the day into distinguishable regions.
CLUSTER_SIM = 0.62
# An edge needs to be walked twice before it's drawn. Once is a passing move.
MIN_EDGE_WEIGHT = 2


def _local_day_bounds(day: datetime) -> tuple[str, str]:
    """UTC bounds for a LOCAL calendar day.

    Timestamps are stored UTC, so `date(ts)` is a UTC day and would silently
    slice the evening off the user's day (and staple it onto the next one). The
    digest learned this already; the map has to agree with it or "today" means
    two different things in two places in the same window.
    """
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    fmt = "%Y-%m-%d %H:%M:%S"
    return (start.astimezone(timezone.utc).strftime(fmt),
            end.astimezone(timezone.utc).strftime(fmt))


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


_TRACKING = re.compile(r"^(utm_|ref$|fbclid|gclid)")
# Unread/notification counters browsers and mail clients staple onto the title —
# "(50) YouTube", "Inbox (1)". They change every few minutes and carry nothing.
_COUNTER = re.compile(r"^\s*[\(\[]\s*\d+\s*[\)\]]\s*|\s*[\(\[]\s*\d+\s*[\)\]]\s*$")
# Titles that name browser chrome rather than a place. A new tab is not somewhere
# you were, and it lands high in dwell because it sits open while you think.
_JUNK_TITLE = re.compile(
    r"^(,?\s*(new tab|untitled|blank|start page|home|loading|about:blank)\s*,?)$", re.I)
# A profile / workspace prefix the browser puts in front of EVERY title in that
# space ("Personal: …", "Work: …"). Detected from the day's data rather than
# hardcoded — see _strip_shared_prefixes — because the names are the user's own.
_PREFIX = re.compile(r"^([^\s:][^:]{0,14}):\s+")


# macOS hands back the tab title the window is currently WIDE ENOUGH to show, so
# the same page yields 'Delta: (50) Srimanthudu…' (24 chars) from one capture and
# the full 114-char title from another. An ellipsis ending is the tell.
_TRUNCATED = re.compile(r"[…]$|\.\.\.$")
# The site name browsers append: " - YouTube", " | GitHub". Letters/dots/spaces
# only and short — so it can never eat " - 7.2)" out of "Chapter 7 TEST (7.1 - 7.2)",
# which is content, or any tail carrying a number.
_SITE_SUFFIX = re.compile(r"\s+[-–—|]\s+[A-Za-z][A-Za-z.\s]{0,20}$")


def _clean_title(t: str) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    # Counters can sit after a profile prefix ("Delta: (50) …"), so strip them
    # wherever they lead a segment, not only at the very start of the string.
    t = re.sub(r"(^|:\s*)[\(\[]\s*\d+\s*[\)\]]\s*", r"\1", t)
    t = _COUNTER.sub("", t)
    return t.strip(" ,·|-–—…").strip()


def _drop_site_suffix(title: str) -> str:
    """Remove the trailing site name, but never at the cost of real content."""
    stripped = _SITE_SUFFIX.sub("", title).strip()
    # Refuse a cut that leaves an unclosed bracket — that means the "suffix" was
    # part of a parenthetical, not a site name.
    if len(stripped) >= 6 and stripped.count("(") == stripped.count(")"):
        return stripped
    return title


def _strip_shared_prefixes(nodes: list[dict]) -> None:
    """Remove a "Profile: " prefix that shows up across unrelated places.

    Dia (and Chrome profiles, and some mail clients) prefix every window title
    with the space it belongs to, so a whole day of labels reads "Personal: …",
    "Work: …" — the prefix is the least informative part of every label and it
    costs the width that the actual name needs. It cannot be a hardcoded list
    because the names are whatever the user called their spaces, so infer it: a
    prefix shared by three or more DIFFERENT places is a container, not content.
    """
    counts: dict[str, int] = {}
    for n in nodes:
        m = _PREFIX.match(n["label"])
        if m:
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    # Two is enough: a browser space name shows up on everything in that space,
    # and a day often only has two or three places per space.
    shared = {p for p, c in counts.items() if c >= 2}
    if not shared:
        return
    for n in nodes:
        m = _PREFIX.match(n["label"])
        if m and m.group(1) in shared:
            stripped = n["label"][m.end():].strip()
            if len(stripped) >= 3:            # never strip a label into nothing
                n["label"] = stripped


def _ellipsize(s: str, limit: int) -> str:
    """Cut at a word boundary — a label chopped mid-word reads as corruption."""
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0]
    return (cut if len(cut) >= limit * 0.6 else s[:limit]).rstrip(" ,-–—|") + "…"


def _label_for(page_key: str, titles: list[str], app: str) -> str:
    """A human name for a place.

    `page_key` is built for identity, not for reading — "antigravity ide::rewisp
    — build re" or a bare URL path. The window title is what the user actually
    saw in their own tab bar, so prefer the most common one and fall back to the
    URL shape only when there is no title at all.
    """
    raw = [t for t in titles if t and not _JUNK_TITLE.match(_clean_title(t))]
    # Prefer a title macOS did NOT truncate. Frequency is the wrong signal here:
    # the narrow, elided version is usually the most common one, so ranking by
    # count reliably picked '…' over the full name of the same page.
    whole = [t for t in raw if not _TRUNCATED.search(t.strip())]
    pool = whole or raw
    if pool:
        best: dict[str, int] = {}
        for t in pool:
            best[t] = best.get(t, 0) + 1
        # Among complete titles the most frequent wins; ties go to the LONGER one,
        # since the longer complete title is the one that survived elision.
        title = _clean_title(sorted(best, key=lambda t: (-best[t], -len(t)))[0])
        title = _drop_site_suffix(title)
        # Pipe-separated titles are "Real Name | credit | credit" (YouTube, news).
        # The first segment is the name; the rest is metadata that would push
        # every other label off the map. Applied at ANY length, not just long
        # ones — a title that has already been shortened by dropping its site
        # suffix still carries the credits, and it is the same noise either way.
        # The 12-char floor protects real short heads ("Inbox | Gmail").
        if " | " in title:
            head = title.split(" | ", 1)[0].strip()
            if len(head) >= 12:
                title = head
        if len(title) >= 3:
            return _ellipsize(title, 48)
    if page_key.startswith("http"):
        s = urlsplit(page_key)
        host = s.netloc.replace("www.", "")
        tail = [p for p in s.path.split("/") if p and not _TRACKING.match(p)]
        return (f"{host}/{tail[-1]}" if tail else host)[:48]
    return (page_key.split("::", 1)[-1] or app or page_key)[:48]


def _mds_2d(mat):
    """Classical MDS of unit-norm rows into 2D — the layout, in ~10 lines.

    Cosine distance -> double-centred Gram matrix -> top two eigenvectors. It is
    deterministic (no random init, no seed to drift), which matters more here
    than projection quality: the map is a place the user learns, and a layout
    that reshuffles itself on every refresh is worse than no layout at all. At
    <=18 points the eigendecomposition is microseconds, so nothing fancier
    (UMAP, t-SNE, and their extra dependency + randomness) earns its place.
    """
    import numpy as np
    n = len(mat)
    if n == 1:
        return np.zeros((1, 2))
    if n == 2:
        return np.array([[-1.0, 0.0], [1.0, 0.0]])
    d = 1.0 - (mat @ mat.T)              # cosine distance, rows are unit-norm
    np.fill_diagonal(d, 0.0)
    d2 = d ** 2
    j = np.eye(n) - np.ones((n, n)) / n
    b = -0.5 * j @ d2 @ j                # double-centred
    vals, vecs = np.linalg.eigh(b)
    idx = np.argsort(vals)[::-1][:2]
    coords = vecs[:, idx] * np.sqrt(np.maximum(vals[idx], 0))
    # Deterministic orientation: eigenvectors are sign-ambiguous, so the same day
    # could mirror between two runs. Pin the sign by the widest-spread axis.
    for k in range(2):
        col = coords[:, k]
        if col[np.argmax(np.abs(col))] < 0:
            coords[:, k] = -col
    return coords


def _spread(coords, min_gap: float = 0.18, iterations: int = 60):
    """Push overlapping dots apart without destroying the meaning of the layout.

    MDS happily stacks near-identical pages on the same pixel (three tabs of the
    same doc are genuinely the same point), which hides nodes behind each other.
    A few rounds of pairwise repulsion separate them enough to click while the
    global arrangement — which is the part that carries meaning — barely moves.
    """
    import numpy as np
    c = np.array(coords, dtype=np.float64)
    n = len(c)
    if n < 2:
        return c
    span = max(float(np.abs(c).max()), 1e-6)
    c /= span                                   # normalise before using min_gap
    for _ in range(iterations):
        moved = False
        for i in range(n):
            for k in range(i + 1, n):
                delta = c[i] - c[k]
                dist = float(np.linalg.norm(delta))
                if dist >= min_gap:
                    continue
                moved = True
                if dist < 1e-9:                 # exactly coincident: split them
                    ang = 2 * math.pi * (i * 7 + k * 13) / max(n * 20, 1)
                    delta = np.array([math.cos(ang), math.sin(ang)])
                    dist = 1e-9
                push = (delta / dist) * (min_gap - dist) / 2
                c[i] += push
                c[k] -= push
        if not moved:
            break
    # Normalise each axis to its OWN range rather than dividing both by one
    # global maximum. MDS's second eigenvalue is routinely a fraction of the
    # first, so a uniform scale left every node squeezed into a horizontal band
    # with the top and bottom of the canvas empty — the layout was correct and
    # unreadable. Stretching per axis costs strict distance fidelity, which this
    # picture never claimed: what has to survive is *which things sit together*,
    # and that is preserved by an axis-aligned scale.
    for axis in (0, 1):
        col = c[:, axis]
        lo, hi = float(col.min()), float(col.max())
        span = hi - lo
        if span < 1e-6:
            c[:, axis] = 0.0                    # degenerate axis: keep it centred
        else:
            c[:, axis] = (col - lo) / span * 2.0 - 1.0
    return c


def _cluster(mat, threshold: float = CLUSTER_SIM) -> list[int]:
    """Connected components over cosine similarity — the colour groups.

    Single-link on purpose: topics genuinely chain (a doc, its repo, the search
    that found it), and at this scale the failure mode of single-link
    (everything merging) is bounded by there being at most 18 nodes.
    """
    import numpy as np
    n = len(mat)
    sim = mat @ mat.T
    np.fill_diagonal(sim, 0.0)
    label = [-1] * n
    current = 0
    for i in range(n):
        if label[i] != -1:
            continue
        stack, label[i] = [i], current
        while stack:
            j = stack.pop()
            for k in np.where(sim[j] >= threshold)[0]:
                if label[k] == -1:
                    label[k] = current
                    stack.append(int(k))
        current += 1
    return label


def day_map(conn, day: datetime | None = None) -> dict:
    """The whole picture for one local day.

    Returns {date, nodes, edges, trace, totals}. Every coordinate is already
    normalised to roughly [-1, 1] so the UI only has to scale to its canvas —
    layout is a data decision, not a drawing decision, and keeping it here means
    the same map can be rendered by the Swift view, a test, or an export.
    """
    import numpy as np
    day = day or datetime.now().astimezone()
    since, until = _local_day_bounds(day)
    rows = conn.execute(
        "SELECT id, ts, app, window_title, url, page_key, embedding FROM captures "
        "WHERE ts >= ? AND ts < ? AND page_key IS NOT NULL ORDER BY ts",
        (since, until)).fetchall()
    empty = {"date": day.strftime("%Y-%m-%d"), "nodes": [], "edges": [],
             "trace": [], "totals": {"captures": 0, "pages": 0, "minutes": 0}}
    if not rows:
        return empty

    # -- dwell, visits, and the raw material for a label, per place -------------
    places: dict[str, dict] = {}
    for i, (rid, ts, app, title, url, pkey, emb) in enumerate(rows):
        p = places.setdefault(pkey, {
            "page_key": pkey, "app": app or "", "url": url, "titles": [],
            "dwell": 0.0, "visits": 0, "first": ts, "last": ts,
            "vecs": [], "peak_wisp": rid})
        p["last"] = ts
        p["visits"] += 1
        if title:
            p["titles"].append(title)
        if url and not p["url"]:
            p["url"] = url
        if emb is not None:
            p["vecs"].append(np.frombuffer(emb, dtype=np.float32))
        if i + 1 < len(rows):
            gap = (_parse(rows[i + 1][1]) - _parse(ts)).total_seconds()
            p["dwell"] += min(max(gap, 0.0), DWELL_CAP_SECONDS)

    # -- keep only the places that actually held the day -----------------------
    for p in places.values():
        p["label"] = _label_for(p["page_key"], p["titles"], p["app"])
    ranked = sorted(places.values(), key=lambda p: -p["dwell"])
    # A new tab left open while you think accrues real dwell but is not a place
    # you were, so it would take a dot and a label away from one that is.
    #
    # Checked against the TITLES as well as the final label, not just the label:
    # _label_for discards junk titles and falls back to the page_key, which can
    # launder ", New Tab," into something that no longer looks like junk.
    def _is_junk(p: dict) -> bool:
        if _JUNK_TITLE.match(p["label"]):
            return True
        cleaned = [_clean_title(t) for t in p["titles"] if t and t.strip()]
        return bool(cleaned) and all(_JUNK_TITLE.match(c) for c in cleaned)

    ranked = [p for p in ranked if not _is_junk(p)]
    kept = [p for p in ranked if p["dwell"] >= MIN_DWELL_SECONDS][:MAX_NODES]
    if not kept:
        kept = ranked[:3]                    # a very light day still gets a map
    kept = [p for p in kept if p["vecs"]]    # no vector, no position
    if not kept:
        return empty

    mat = np.vstack([
        (lambda v: v / (np.linalg.norm(v) + 1e-9))(np.mean(p["vecs"], axis=0))
        for p in kept])
    coords = _spread(_mds_2d(mat))
    clusters = _cluster(mat)

    index = {p["page_key"]: i for i, p in enumerate(kept)}
    nodes = []
    for i, p in enumerate(kept):
        nodes.append({
            "id": i,
            "page_key": p["page_key"],
            "label": p["label"],
            "app": p["app"],
            "url": p["url"],
            "minutes": round(p["dwell"] / 60.0, 1),
            "visits": p["visits"],
            "first": p["first"],
            "last": p["last"],
            "wisp_id": p["peak_wisp"],
            "cluster": int(clusters[i]),
            "x": round(float(coords[i][0]), 4),
            "y": round(float(coords[i][1]), 4),
        })
    _strip_shared_prefixes(nodes)

    # -- edges: how often you moved between two places -------------------------
    # This is the part a scrubber structurally cannot show. A thick edge is a
    # loop you were caught in, and you cannot feel it from the inside.
    weights: dict[tuple[int, int], int] = {}
    trace: list[dict] = []
    prev_idx = None
    for _rid, ts, _app, _t, _u, pkey, _e in rows:
        idx = index.get(pkey)
        if idx is None:
            continue                          # a filtered-out place breaks no edge
        if idx != prev_idx:
            trace.append({"node": idx, "ts": ts})
            if prev_idx is not None:
                weights[(min(prev_idx, idx), max(prev_idx, idx))] = \
                    weights.get((min(prev_idx, idx), max(prev_idx, idx)), 0) + 1
            prev_idx = idx
    edges = [{"a": a, "b": b, "weight": w}
             for (a, b), w in sorted(weights.items(), key=lambda kv: -kv[1])
             if w >= MIN_EDGE_WEIGHT]

    return {
        "date": day.strftime("%Y-%m-%d"),
        "nodes": nodes,
        "edges": edges,
        "trace": trace,
        "totals": {
            "captures": len(rows),
            "pages": len(places),
            "minutes": round(sum(p["dwell"] for p in places.values()) / 60.0),
        },
    }


def reinstate(conn, page_key: str, at: str | None = None) -> dict | None:
    """Put the user back in a moment — the card behind a tap on the map.

    Context reinstatement is the strongest recall effect in the literature
    (VR study PMC9732332: +16 points at one week, 38% fewer false memories), but
    it comes with a hard condition — it only works if the cue creates *presence*.
    A list of timestamps does not. So this rebuilds the scene: what was on the
    screen, when, and — the part that does the real work — what you were doing
    immediately before and after, which is the cue people actually retain when
    they have offloaded the content itself (Sparrow/Wegner 2011).
    """
    where = "page_key = ?"
    params: list = [page_key]
    if at:
        where += " AND ts <= ?"
        params.append(at)
    row = conn.execute(
        f"SELECT id, ts, app, window_title, url, ocr_text FROM captures "
        f"WHERE {where} ORDER BY ts DESC LIMIT 1", params).fetchone()
    if not row:
        return None
    rid, ts, app, title, url, text = row

    from . import dream
    lines = dream._salient_lines([text or ""], limit=6)

    def _neighbour(direction: str) -> dict | None:
        """The nearest capture on a DIFFERENT page — where you came from, or
        went next. Same-page neighbours are the same moment and cue nothing."""
        op, order = ("<", "DESC") if direction == "before" else (">", "ASC")
        r = conn.execute(
            f"SELECT ts, app, window_title, url, page_key FROM captures "
            f"WHERE id {op} ? AND page_key IS NOT NULL AND page_key != ? "
            f"ORDER BY id {order} LIMIT 1", (rid, page_key)).fetchone()
        if not r:
            return None
        n_ts, n_app, n_title, n_url, n_key = r
        gap = abs((_parse(n_ts) - _parse(ts)).total_seconds()) / 60.0
        if gap > 90:
            return None                       # too far away to be the same thread
        return {"label": _label_for(n_key, [n_title or ""], n_app or ""),
                "app": n_app, "ts": n_ts, "url": n_url,
                "minutes_away": round(gap, 1)}

    return {
        "wisp_id": rid,
        "page_key": page_key,
        "ts": ts,
        "app": app,
        "title": title,
        "url": url,
        "label": _label_for(page_key, [title or ""], app or ""),
        "lines": lines,
        "before": _neighbour("before"),
        "after": _neighbour("after"),
    }
