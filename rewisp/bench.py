"""Answer-quality benchmark with a calculated accuracy score.

Runs the same questions against every engine you have set up — including the real
Apple on-device model (via the compiled ui/AppleAsk bridge) — then has Claude act
as an impartial judge, scoring each answer 0-100 for how correct and grounded it is
versus the retrieved context. Prints per-question scores and a final scoreboard.

    python3 -m rewisp bench                 # default question set, graded
    python3 -m rewisp bench "q1" "q2" ...   # your own questions
    python3 -m rewisp bench --file q.txt    # one question per line
    python3 -m rewisp bench --no-grade      # just show answers, skip scoring

Each engine gets the prompt it uses in production: Apple gets the compact prompt,
cloud/local engines get the full-context prompt. The judge (Claude) sees the full
context as ground truth. Note: Claude is also a candidate, so treat its own score
as a soft ceiling — the headline comparison is Apple vs Gemini.
"""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import ask, config, db

DEFAULT_QUESTIONS = [
    "what was I doing an hour ago?",
    "what websites did I visit today?",
    "what was the last thing I read?",
    "what code file was I editing most recently?",
    "what did I search for today?",
    "what apps did I use most today?",
    "summarize what I worked on this morning",
    "was there anything I need to follow up on?",
]

APPLE_BIN = os.environ.get("REWISP_APPLE_BIN") or str(
    Path(__file__).resolve().parent.parent / "ui" / "AppleAsk")


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _available() -> list[str]:
    """Engines this harness can call right now. Apple first — it's the one on trial."""
    import urllib.request
    out = []
    if os.path.exists(APPLE_BIN):
        out.append("apple")
    if ask.cli_path("claude"):
        out.append("claude")
    if ask.cli_path("codex"):
        out.append("codex")
    from . import localmodel
    if localmodel.active_model():
        out.append("local")
    if (config.load_settings().get("gemini_api_key") or "").strip():
        out.append("gemini")
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1)
        out.append("ollama")
    except OSError:
        pass
    # REWISP_BENCH_ENGINES=apple,local restricts candidates (e.g. to conserve a
    # rate-limited cloud key, or focus a comparison).
    only = os.environ.get("REWISP_BENCH_ENGINES")
    if only:
        keep = {e.strip() for e in only.split(",")}
        out = [e for e in out if e in keep]
    return out


def _call_apple(prompt: str) -> str:
    out = subprocess.run([APPLE_BIN], input=prompt, capture_output=True,
                         text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or "apple model failed").strip()[:120])
    return out.stdout.strip()


def _run(name: str, prompt: str) -> tuple[dict, float, str | None]:
    t0 = time.time()
    try:
        raw = _call_apple(prompt) if name == "apple" else ask.ENGINES[name](prompt)
        return ask.parse_answer(raw), time.time() - t0, None
    except Exception as e:  # noqa: BLE001 — a failing engine is a datapoint
        return {}, time.time() - t0, str(e)[:120]


def _judge(context: str, question: str, answers: dict[str, str]) -> dict[str, int]:
    """Grade each answer in its OWN call — batched grading proved erratic (the
    judge scored strong answers 0). One answer, one reasoning step, one score."""
    scores = {}
    for e, a in answers.items():
        s = _grade_one(context, question, a)
        if s is not None:
            scores[e] = s
    return scores


def _grade_one(context: str, question: str, answer: str) -> int | None:
    if not answer or answer == "(empty)":
        return 0
    prompt = (
        "You grade ONE answer to a question about a user's screen history. The "
        "CONTEXT is the ONLY source of truth: a claim not supported by CONTEXT is "
        "wrong, however plausible it sounds.\n\n"
        "Step 1: in one sentence, state whether every specific claim in the ANSWER "
        "(names, apps, titles, numbers) actually appears in the CONTEXT.\n"
        "Step 2: output a final line exactly `SCORE: <0-100>` using this scale:\n"
        "  100 = fully correct and every claim supported by CONTEXT\n"
        "  60  = partially correct, vague, or thin but not wrong\n"
        "  0   = wrong, OR asserts a specific fact absent from CONTEXT (hallucination)\n"
        "  90  = CONTEXT genuinely lacks the answer AND the answer says so (\"not found\")\n\n"
        f"CONTEXT:\n{context[:12000]}\n\nQUESTION: {question}\n\nANSWER: {answer}\n")
    raw = _judge_call(prompt)
    if raw is None:
        return None
    m = re.search(r"score:\s*(\d{1,3})", raw.lower())
    return max(0, min(100, int(m.group(1)))) if m else None


# Judge with Claude (best); if it's rate-limited/unavailable, fall back to Gemini
# so a benchmark can still produce numbers. Cached so we don't re-probe every call.
_JUDGE = {"engine": None}


def judge_engine() -> str | None:
    if _JUDGE["engine"] is None:
        if ask.cli_path("claude"):
            _JUDGE["engine"] = "claude"
        elif (config.load_settings().get("gemini_api_key") or "").strip():
            _JUDGE["engine"] = "gemini"
        else:
            _JUDGE["engine"] = "none"
    return None if _JUDGE["engine"] == "none" else _JUDGE["engine"]


def _judge_call(prompt: str) -> str | None:
    order = ["claude", "gemini"] if judge_engine() == "claude" else ["gemini", "claude"]
    for eng in order:
        try:
            return ask.ENGINES[eng](prompt)
        except Exception:  # noqa: BLE001 — try the next judge
            continue
    print("    (judge unavailable: no working judge engine)")
    return None


def run(questions: list[str] | None = None, grade: bool = True) -> None:
    questions = questions or DEFAULT_QUESTIONS
    engines = _available()
    if not engines:
        print("No engines available. Build ui/AppleAsk, sign into `claude`/`codex`, "
              "set a Gemini key, or start Ollama, then rerun.")
        return
    if grade and not judge_engine():
        print("Grading needs a judge (Claude or Gemini). Falling back to answers only.\n")
        grade = False
    print(f"engines: {', '.join(engines)}" + (f"   judge: {judge_engine()}" if grade else ""))
    print(f"questions: {len(questions)}\n" + "=" * 74)

    conn = db.connect()
    totals: dict[str, list[int]] = {e: [] for e in engines}
    try:
        for qi, q in enumerate(questions, 1):
            context, meta = ask.build_context(conn, q, compact=False)
            full_prompt, _ = ask.build_prompt(q, compact=False)
            compact_prompt, _ = ask.build_prompt(q, compact=True)
            print(f"\nQ{qi}. {q}    [{meta.get('n_captures', 0)} captures matched]")
            answers = {}
            for e in engines:
                prompt = compact_prompt if e == "apple" else full_prompt
                fields, dt, err = _run(e, prompt)
                if err:
                    print(f"  {e:<8} !! {err}  ({dt:.1f}s)")
                    answers[e] = ""
                    continue
                ans = _norm(fields.get("answer")) or "(empty)"
                answers[e] = ans
                print(f"  {e:<8} {ans[:150]}  ({dt:.1f}s)")
            if grade:
                scores = _judge(context, q, answers)
                if scores:
                    line = "  score:  " + "   ".join(
                        f"{e} {scores.get(e, '?')}" for e in engines)
                    print(line)
                    for e in engines:
                        if e in scores:
                            totals[e].append(scores[e])
    finally:
        conn.close()

    if not grade:
        return
    print("\n" + "=" * 74)
    print("SCOREBOARD — mean accuracy (0-100), judged by Claude vs your real memory\n")
    ranked = sorted(engines, key=lambda e: -_mean(totals[e]))
    for e in ranked:
        vals = totals[e]
        if not vals:
            print(f"  {e:<8}  no scores")
            continue
        bar = "█" * round(_mean(vals) / 4)
        print(f"  {e:<8}  {_mean(vals):5.1f}  {bar}  (n={len(vals)})")
    # Headline: Apple vs Gemini, the two the user cares about.
    if totals.get("apple") and totals.get("gemini"):
        a, g = _mean(totals["apple"]), _mean(totals["gemini"])
        d = g - a
        better = "Gemini" if d > 0 else "Apple on-device"
        print(f"\n  Apple on-device: {a:.1f}    Gemini: {g:.1f}")
        print(f"  Difference: {abs(d):.1f} points in favour of {better} "
              f"({abs(d) / max(a, 1) * 100:.0f}% relative).")
    j = judge_engine()
    if j in engines:
        print(f"\n  Note: {j} is also the judge, so read its own score as a ceiling, "
              "not a peer result.")
    else:
        print(f"\n  Judge: {j}.")


def _mean(v: list[int]) -> float:
    return sum(v) / len(v) if v else 0.0


def main(args: list[str]) -> None:
    grade = "--no-grade" not in args
    args = [a for a in args if a != "--no-grade"]
    if args and args[0] == "--file":
        if len(args) < 2:
            print("usage: bench --file questions.txt")
            return
        with open(args[1]) as f:
            run([ln.strip() for ln in f if ln.strip()], grade=grade)
    elif args:
        run(list(args), grade=grade)
    else:
        run(grade=grade)


if __name__ == "__main__":
    main(sys.argv[1:])


# ── OCR shadow A/B verdict ───────────────────────────────────────────────────
#
# The macOS 26 document recogniser has been implemented, signed and shipped
# switched off since v0.25, together with a shadow mode that runs BOTH engines on
# every capture and logs metrics (never screen text). What never existed was the
# thing that turns that log into a decision, so the comparison was never run and
# the faster engine sat unused behind an env var.
#
# Usage:
#   REWISP_OCR_SHADOW=1  (restart the daemon, browse normally for a while)
#   python3 -m rewisp ocr-ab

def ocr_ab(limit: int = 0) -> dict:
    """Summarise ~/Rewisp/ocr_ab.jsonl into a recommendation."""
    import json as _json
    from . import config

    path = config.OCR_AB_LOG
    if not path.exists():
        return {"records": 0,
                "verdict": "No A/B log yet. Set REWISP_OCR_SHADOW=1 for the daemon, "
                           "restart it, use your Mac normally for an hour, then re-run."}
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(_json.loads(line))
        except ValueError:
            continue
    if limit:
        rows = rows[-limit:]
    ok = [r for r in rows if r.get("swift_ok")]
    if not ok:
        return {"records": len(rows),
                "verdict": "The document engine never returned anything — it needs "
                           "macOS 26 and the bundled rewisp-ocr helper. Keep the "
                           "tiled path."}

    def mean(key):
        vals = [r.get(key, 0) or 0 for r in ok]
        return sum(vals) / max(len(vals), 1)

    out = {
        "records": len(rows),
        "comparable": len(ok),
        "helper_failed": len(rows) - len(ok),
        "chars":   {"tiled": round(mean("tiled_chars")),   "swift": round(mean("swift_chars"))},
        "lines":   {"tiled": round(mean("tiled_lines"), 1), "swift": round(mean("swift_lines"), 1)},
        "doubled": {"tiled": round(mean("tiled_doubled"), 2), "swift": round(mean("swift_doubled"), 2)},
        "ms":      {"tiled": round(mean("tiled_ms")),      "swift": round(mean("swift_ms"))},
        "overlap": round(mean("overlap"), 3),
    }
    # A recommendation, with the reasoning stated — the point is to decide, and a
    # table of numbers is what let this sit undecided for five releases.
    reasons = []
    faster = out["ms"]["swift"] < out["ms"]["tiled"] * 0.9
    # Strictly better, not merely equal — a tie on every metric is not a reason
    # to change the engine that reads every screen you will ever see.
    cleaner = out["doubled"]["swift"] < out["doubled"]["tiled"]
    worse_doubling = out["doubled"]["swift"] > out["doubled"]["tiled"] * 1.5
    # Recall is the one that must not regress: a faster engine that reads less of
    # the screen makes every future answer worse, and silently.
    keeps_text = out["chars"]["swift"] >= out["chars"]["tiled"] * 0.95
    agrees = out["overlap"] >= 0.85

    if faster:
        reasons.append(f"{out['ms']['tiled'] / max(out['ms']['swift'], 1):.1f}x faster")
    if cleaner:
        reasons.append("no more doubling")
    if not keeps_text:
        reasons.append(f"reads {100 * (1 - out['chars']['swift'] / max(out['chars']['tiled'], 1)):.0f}% LESS text")
    if not agrees:
        reasons.append(f"only {out['overlap']:.0%} word overlap — the engines disagree about content")

    if worse_doubling:
        reasons.append(f"doubles words {out['doubled']['swift'] / max(out['doubled']['tiled'], 0.01):.1f}x more")
    if keeps_text and agrees and not worse_doubling and (faster or cleaner):
        out["verdict"] = ("SWITCH IT ON — set OCR_USE_DOCUMENTS = True in config.py. "
                          + ", ".join(reasons))
    elif not keeps_text or not agrees or worse_doubling:
        out["verdict"] = "KEEP THE TILED PATH — " + ", ".join(reasons)
    else:
        out["verdict"] = "No clear win. Keep the tiled path; nothing to gain."
    if out["comparable"] < 100:
        out["verdict"] += (f"  (only {out['comparable']} comparable captures — "
                           "collect a few hundred before trusting this)")
    return out
