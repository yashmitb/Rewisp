#!/bin/zsh
# How many people are actually downloading Rewisp.
#
#   ./scripts/stats.sh
#
# Reads GitHub's own counters. No tracking script, no third party, nothing added
# to the site — GitHub already counts every asset download and every repo view,
# and asking it costs the visitor nothing.
set -u

REPO="yashmitb/Rewisp"

echo "── downloads ──"
curl -s "https://api.github.com/repos/$REPO/releases?per_page=100" | python3 -c '
import sys, json, datetime
rels = json.load(sys.stdin)
if not isinstance(rels, list):
    print("  (rate limited — try again in a few minutes)"); raise SystemExit
total = 0
by_day = {}
rows = []
for r in sorted(rels, key=lambda x: x["published_at"]):
    n = sum(a["download_count"] for a in r["assets"])
    total += n
    day = r["published_at"][:10]
    by_day[day] = by_day.get(day, 0) + n
    if n:
        rows.append((r["tag_name"], day, n))
for tag, day, n in rows[-12:]:
    bar = "#" * min(40, n)
    print(f"  {tag:<10} {day}  {n:>5}  {bar}")
print(f"\n  TOTAL: {total} downloads across {len(rels)} releases")
if by_day:
    best = max(by_day.items(), key=lambda kv: kv[1])
    print(f"  best day: {best[0]} ({best[1]})")
'

echo ""
echo "── repo traffic (GitHub keeps only the last 14 days) ──"
gh api "repos/$REPO/traffic/views" \
   --jq "\"  views:  \(.count) total, \(.uniques) unique\"" 2>/dev/null \
   || echo "  (run: gh auth login — traffic needs repo access)"
gh api "repos/$REPO/traffic/clones" \
   --jq "\"  clones: \(.count) total, \(.uniques) unique\"" 2>/dev/null || true

echo ""
echo "── where visitors came from ──"
gh api "repos/$REPO/traffic/popular/referrers" \
   --jq '.[] | "  \(.referrer): \(.count) (\(.uniques) unique)"' 2>/dev/null \
   || echo "  (none recorded)"

echo ""
echo "── stars & watchers ──"
gh api "repos/$REPO" \
   --jq '"  stars: \(.stargazers_count)  forks: \(.forks_count)  watchers: \(.subscribers_count)  issues: \(.open_issues_count)"' \
   2>/dev/null || true
