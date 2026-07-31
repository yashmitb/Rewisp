"""Render the day map to SVG, mirroring the rules ui/Sources/Constellation.swift
draws with.

The day map went through three visual revisions that could only be judged by
building a DMG, installing it, and looking — which meant every round trip cost a
release and the person on the other end was doing the seeing. This closes that
loop: the layout, the label placement and collision behaviour, the edge density
and the contrast can all be checked against real data in a second.

Not pixel-identical to SwiftUI (it approximates text metrics, and it draws the
nebulae as flat discs rather than radial gradients, so they look harder here than
they do in the app). It reproduces the things that have actually gone wrong.

    ./scripts/preview_daymap.py [days_back] [hovered_node_id] [out.svg]

Needs the bundled runtime, since the database is encrypted:

    APP=/Applications/Rewisp.app/Contents
    PYTHONHOME=$APP/Resources/python PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 \
      $APP/Resources/python/bin/python3 scripts/preview_daymap.py 1

Then `qlmanage -t -s 1400 -o . map.svg` to get a PNG.

PYTHONDONTWRITEBYTECODE matters: anything written inside the app bundle
invalidates its signature and macOS withdraws the Screen Recording grant.
"""
import html
import sys
from datetime import datetime, timedelta

from rewisp import db, constellation

W, H = 1150, 296
H_INSET, V_INSET = 86, 42
MAX_LABELS = 9

CLUSTER = ["#8EA3FF", "#B08CFF", "#70D4FF", "#8CEDD1", "#FFC48E", "#FF9EC7", "#CCF294"]


def hue(c):
    return CLUSTER[abs(c) % len(CLUSTER)]


def layout(nodes):
    w = W - H_INSET * 2
    h = H - V_INSET * 2 - 12
    return {n["id"]: (H_INSET + (n["x"] + 1) / 2 * w,
                      V_INSET + (n["y"] + 1) / 2 * h) for n in nodes}


def radius(n):
    return min(5 + (max(n["minutes"], 0) ** 0.5) * 1.9, 23)


def measure(text, size):
    """Rough text metrics — enough to reproduce the collision behaviour."""
    return (len(text) * size * 0.55, size * 1.25)


def rects_overlap(a, b):
    return not (a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0]
                or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1])


def render(m, hovered=None):
    pts = layout(m["nodes"])
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}">']
    # Card surface, approximating .quaternary.opacity(0.28) over the window.
    out.append(f'<rect width="{W}" height="{H}" fill="#1c1d22"/>')
    out.append(f'<defs><radialGradient id="g1"><stop offset="0" stop-color="#8EA3FF" '
               f'stop-opacity="0.07"/><stop offset="1" stop-color="#8EA3FF" stop-opacity="0"/>'
               f'</radialGradient><radialGradient id="g2"><stop offset="0" stop-color="#B08CFF" '
               f'stop-opacity="0.06"/><stop offset="1" stop-color="#B08CFF" stop-opacity="0"/>'
               f'</radialGradient></defs>')
    out.append(f'<ellipse cx="{0.20*W}" cy="{0.18*H}" rx="300" ry="300" fill="url(#g1)"/>')
    out.append(f'<ellipse cx="{0.84*W}" cy="{0.86*H}" rx="320" ry="320" fill="url(#g2)"/>')

    # nebulae
    groups = {}
    for n in m["nodes"]:
        groups.setdefault(n["cluster"], []).append(pts[n["id"]])
    for cl, ps in groups.items():
        if len(ps) < 2:
            continue
        cx = sum(p[0] for p in ps) / len(ps)
        cy = sum(p[1] for p in ps) / len(ps)
        spread = max(((p[0]-cx)**2 + (p[1]-cy)**2) ** 0.5 for p in ps)
        r = spread + 34
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{hue(cl)}" '
                   f'opacity="0.043"/>')

    # edges — top 6 at rest
    maxw = m["edges"][0]["weight"] if m["edges"] else 1
    resting = m["edges"][:6]
    for e in (m["edges"] if hovered is not None else resting):
        a, b = pts[e["a"]], pts[e["b"]]
        touches = hovered in (e["a"], e["b"])
        if hovered is not None and not touches and e not in resting:
            continue
        s = e["weight"] / max(maxw, 1)
        base = (0.22 + 0.38 * s) if touches else (0.05 + 0.07 * s) * (1 if hovered is None else 0.25)
        lw = (0.9 + s * 2.4) if touches else (0.5 + s * 1.0)
        mx, my = (a[0]+b[0])/2, (a[1]+b[1])/2
        nx, ny = -(b[1]-a[1]), b[0]-a[0]
        ln = max((nx*nx+ny*ny) ** 0.5, 1)
        bow = 0.14 * ((b[0]-a[0])**2 + (b[1]-a[1])**2) ** 0.5
        out.append(f'<path d="M{a[0]:.1f},{a[1]:.1f} Q{mx+nx/ln*bow:.1f},{my+ny/ln*bow:.1f} '
                   f'{b[0]:.1f},{b[1]:.1f}" fill="none" stroke="{hue(m["nodes"][e["a"]]["cluster"])}" '
                   f'stroke-opacity="{base:.3f}" stroke-width="{lw:.2f}"/>')

    # trace — white
    seq = []
    if len(seq) >= 2:
        d = "M" + " L".join(f"{p[0]:.1f},{p[1]:.1f}" for p in seq)
        dim = hovered is not None
        out.append(f'<path d="{d}" fill="none" stroke="#fff" stroke-opacity="'
                   f'{0.05 if dim else 0.12}" stroke-width="5" stroke-linejoin="round"/>')
        out.append(f'<path d="{d}" fill="none" stroke="#fff" stroke-opacity="'
                   f'{0.30 if dim else 0.82}" stroke-width="1.5" stroke-linejoin="round"/>')

    # nodes
    for n in sorted(m["nodes"], key=lambda n: n["minutes"]):
        p = pts[n["id"]]
        r = radius(n)
        hot = hovered == n["id"]
        dim = 1 if (hovered is None or hot) else 0.55
        gr = r * (3.4 if hot else 2.5)
        out.append(f'<circle cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="{gr:.1f}" fill="{hue(n["cluster"])}" '
                   f'opacity="{0.16*dim:.3f}"/>')
        out.append(f'<circle cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="{r:.1f}" fill="{hue(n["cluster"])}" '
                   f'opacity="{0.92*dim:.2f}" stroke="#fff" stroke-opacity="{(0.8 if hot else 0.28)*dim:.2f}" '
                   f'stroke-width="{1.4 if hot else 0.8}"/>')

    # labels
    taken = []
    for n in m["nodes"]:
        p = pts[n["id"]]
        r = radius(n) + 3
        taken.append((p[0]-r, p[1]-r, r*2, r*2))

    cands = sorted([n for n in m["nodes"] if n["id"] != hovered],
                   key=lambda n: -n["minutes"])[:MAX_LABELS]
    if hovered is not None:
        cands.append(next(n for n in m["nodes"] if n["id"] == hovered))

    drawn = 0
    for n in cands:
        p = pts[n["id"]]
        hot = hovered == n["id"]
        dim = 1 if (hovered is None or hot) else 0.62
        size = 11.5 if hot else 10.5
        lab = n["label"] if len(n["label"]) <= 34 else n["label"][:34].rsplit(" ",1)[0]+"…"
        tw, th = measure(lab, size)
        sw = sh = 0
        if hot:
            sw, sh = measure(f'{int(n["minutes"])}m · {n["visits"]} visits', 9.5)
        block_h = th + (sh + 2 if hot else 0)
        block_w = max(tw, sw)
        gap = radius(n) + 9
        options = [(p[0], p[1] + gap), (p[0], p[1] - gap - block_h),
                   (p[0] + gap + block_w/2, p[1] - block_h/2),
                   (p[0] - gap - block_w/2, p[1] - block_h/2),
                   (p[0] + block_w/3, p[1] + gap), (p[0] - block_w/3, p[1] + gap)]
        rect = None
        for ox, oy in options:
            cx = min(max(ox, block_w/2 + 7), W - block_w/2 - 7)
            top = min(max(oy, 5), max(H - block_h - 5, 5))
            cand = (cx - block_w/2 - 6, top - 4, block_w + 12, block_h + 8)
            if hot or not any(rects_overlap(cand, t) for t in taken):
                rect = cand
                break
        if rect is None:
            continue
        cx = rect[0] + rect[2]/2
        top = rect[1] + 4
        taken.append(rect)
        drawn += 1
        out.append(f'<rect x="{rect[0]:.1f}" y="{rect[1]:.1f}" width="{rect[2]:.1f}" '
                   f'height="{rect[3]:.1f}" rx="6" fill="#000" opacity="'
                   f'{0.66 if hot else 0.34*dim:.2f}"/>')
        out.append(f'<text x="{cx:.1f}" y="{top + th*0.75:.1f}" text-anchor="middle" '
                   f'font-family="-apple-system,Helvetica" font-size="{size}" '
                   f'font-weight="{600 if hot else 500}" fill="#fff" '
                   f'fill-opacity="{1.0 if hot else 0.88*dim:.2f}">{html.escape(lab)}</text>')
        if hot:
            out.append(f'<text x="{cx:.1f}" y="{top + th + 2 + sh*0.75:.1f}" text-anchor="middle" '
                       f'font-family="-apple-system,Helvetica" font-size="9.5" fill="#fff" '
                       f'fill-opacity="0.7">{int(n["minutes"])}m · {n["visits"]} visits</text>')
    out.append("</svg>")
    return "\n".join(out), drawn


if __name__ == "__main__":
    back = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    hovered = int(sys.argv[2]) if len(sys.argv) > 2 else None
    c = db.connect()
    m = constellation.day_map(c, datetime.now().astimezone() - timedelta(days=back))
    svg, drawn = render(m, hovered)
    path = sys.argv[3] if len(sys.argv) > 3 else "/tmp/map.svg"
    open(path, "w").write(svg)
    print(f"{m['date']}: {len(m['nodes'])} nodes, {len(m['edges'])} edges, "
          f"{drawn} labels drawn -> {path}")
