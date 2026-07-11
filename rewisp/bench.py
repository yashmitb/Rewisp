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
    import shutil
    import urllib.request
    out = []
    if os.path.exists(APPLE_BIN):
        out.append("apple")
    if shutil.which("claude"):
        out.append("claude")
    if shutil.which("codex"):
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
        import shutil
        if shutil.which("claude"):
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
