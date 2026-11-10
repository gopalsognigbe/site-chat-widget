"""Run the 10 evaluation questions against the running API and report.

    python scripts/run_eval.py

Prints a table (question | pass/fail | latency | sources), writes it to
eval_results.md and refreshes the results table in README.md.
"""

from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from tests.questions import API_URL, CASES, PAUSE_SECONDS, REQUEST_TIMEOUT_SECONDS, Result, api_is_up, ask  # noqa: E402

README_START = "<!-- eval:start -->"
README_END = "<!-- eval:end -->"


def short_source(url: str) -> str:
    return re.sub(r"^https?://[^/]+", "", url)


def table(results: list[Result]) -> str:
    rows = ["| Question | Result | Latency (s) | Sources |", "| --- | --- | ---: | --- |"]
    for r in results:
        verdict = "pass" if r.passed else "FAIL: " + "; ".join(r.failures)
        sources = ", ".join(dict.fromkeys(short_source(u) for u in r.sources)) or "none"
        rows.append(f"| {r.case.question} | {verdict.replace('|', '/')} | {r.latency:.1f} | {sources} |")
    return "\n".join(rows)


def main() -> int:
    if not api_is_up():
        print(f"API not reachable at {API_URL}. Start it with: uvicorn app.main:app --port 8000")
        return 2

    results = []
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        for i, case in enumerate(CASES):
            if i:
                time.sleep(PAUSE_SECONDS)
            result = ask(case, client)
            results.append(result)
            print(f"[{'pass' if result.passed else 'FAIL'}] {case.question} ({result.latency:.1f}s)")

    passed = sum(r.passed for r in results)
    summary = f"{passed}/{len(results)} passed, run {datetime.now():%Y-%m-%d %H:%M} against {API_URL}"
    report = f"{summary}\n\n{table(results)}\n"
    print(f"\n{report}")

    (ROOT / "eval_results.md").write_text(f"# Evaluation results\n\n{report}", encoding="utf-8")

    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    if README_START in text and README_END in text:
        block = f"{README_START}\n{report}{README_END}"
        text = re.sub(re.escape(README_START) + r".*?" + re.escape(README_END), lambda _: block, text, flags=re.S)
        readme.write_text(text, encoding="utf-8")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
