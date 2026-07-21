#!/usr/bin/env python3
"""Read ~/Rewisp/ocr_ab.jsonl (written when REWISP_OCR_SHADOW=1) and print a
verdict: does the Swift document engine actually beat the tiled engine on YOUR
real screens?

The log holds metrics only — no screen text — so this is safe to run and share.

    python3 scripts/ocr_ab_report.py            # ~/Rewisp/ocr_ab.jsonl
    python3 scripts/ocr_ab_report.py <path>
"""

import json
import sys
from collections import Counter
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Rewisp" / "ocr_ab.jsonl"
    if not path.exists():
        print(f"no log at {path}\n"
              f"enable it: set REWISP_OCR_SHADOW=1 for the daemon, use the Mac "
              f"normally for a day, then run this.")
        return 1

    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    if not rows:
        print(f"{path} is empty — no captures logged yet.")
        return 1

    n = len(rows)
    swift_ok = [r for r in rows if r.get("swift_ok")]
    fell_back = n - len(swift_ok)

    def avg(rs, k):
        return sum(r.get(k, 0) for r in rs) / len(rs) if rs else 0

    print(f"captures logged: {n}")
    print(f"swift engine ran: {len(swift_ok)}   fell back to tiled: {fell_back}")
    if not swift_ok:
        print("swift never ran — check the helper binary ships and macOS is 26+.")
        return 1

    print("\n(averages over captures where swift ran)")
    print(f"  chars     tiled {avg(swift_ok,'tiled_chars'):7.0f}   swift {avg(swift_ok,'swift_chars'):7.0f}")
    print(f"  lines     tiled {avg(swift_ok,'tiled_lines'):7.1f}   swift {avg(swift_ok,'swift_lines'):7.1f}")
    print(f"  doubled   tiled {avg(swift_ok,'tiled_doubled'):7.2f}   swift {avg(swift_ok,'swift_doubled'):7.2f}   (lower better)")
    print(f"  time ms   tiled {avg(swift_ok,'tiled_ms'):7.0f}   swift {avg(swift_ok,'swift_ms'):7.0f}")
    print(f"  token overlap (tiled vs swift): {avg(swift_ok,'overlap'):.3f}")

    # Where they disagree most — the screens worth eyeballing live.
    doubling_fixed = sum(1 for r in swift_ok if r["swift_doubled"] < r["tiled_doubled"])
    doubling_worse = sum(1 for r in swift_ok if r["swift_doubled"] > r["tiled_doubled"])
    big_char_drop = sum(1 for r in swift_ok
                        if r["tiled_chars"] and r["swift_chars"] < 0.7 * r["tiled_chars"])
    print(f"\n  captures where swift removed doubling: {doubling_fixed}")
    print(f"  captures where swift ADDED doubling:   {doubling_worse}")
    print(f"  captures where swift read <70% of tiled's chars (possible miss): {big_char_drop}")

    low_overlap = [r for r in swift_ok if r.get("overlap", 1) < 0.7]
    if low_overlap:
        apps = Counter(r.get("app", "") for r in low_overlap)
        print(f"\n  low-overlap apps (engines disagree, look here): "
              f"{', '.join(f'{a}×{c}' for a, c in apps.most_common(6))}")

    # Verdict.
    print("\nverdict:")
    if doubling_worse > doubling_fixed or big_char_drop > 0.1 * len(swift_ok):
        print("  swift is NOT clearly better — keep OCR_USE_DOCUMENTS off, investigate.")
    elif doubling_fixed > 0 and big_char_drop <= 0.02 * len(swift_ok):
        print("  swift removes doubling without losing text — candidate to enable.")
    else:
        print("  roughly even. Little doubling on your screens, so little to gain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
