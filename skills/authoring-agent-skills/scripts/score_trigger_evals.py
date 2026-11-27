#!/usr/bin/env python3
"""Score trigger-eval runs.

Input: JSONL, one line per run: {"query": str, "should_trigger": bool, "triggered": bool}
(run each query ~3 times). A query passes when (trigger rate > 0.5) == should_trigger.
Both flags must be JSON true or false, and every run of a query needs the same should_trigger.
Queries are split 60/40 train/test by a stable hash, so pick descriptions by the TEST score.

Usage: python3 scripts/score_trigger_evals.py runs.jsonl
Exit codes: 0 scored, 2 bad input (also a file with no runs).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", type=Path)
    args = ap.parse_args()
    runs: dict[str, list[bool]] = defaultdict(list)
    expected: dict[str, bool] = {}
    n = 0
    try:
        for n, line in enumerate(args.runs.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                r = json.loads(line)
                q, want, got = r["query"], r["should_trigger"], r["triggered"]
                if not (isinstance(q, str) and isinstance(want, bool) and isinstance(got, bool)):
                    raise ValueError("query must be a string, should_trigger and triggered must be true or false")
                if expected.setdefault(q, want) != want:
                    raise ValueError(f"should_trigger differs from an earlier run of {q!r}")
                runs[q].append(got)
        if not runs:
            raise ValueError("no runs in the file")
    except (OSError, ValueError, KeyError, TypeError) as e:  # ValueError covers bad JSON and bad UTF-8
        print(f"bad input at line {n}: {e}", file=sys.stderr)
        return 2

    split: dict[str, dict] = {"train": defaultdict(int), "test": defaultdict(int)}
    failures = []
    for q, hits in runs.items():
        rate = sum(hits) / len(hits)
        ok = (rate > 0.5) == expected[q]
        bucket = "train" if int(hashlib.sha256(q.encode()).hexdigest(), 16) % 10 < 6 else "test"
        s = split[bucket]
        s["total"] += 1
        s["passed"] += ok
        s[("tp" if ok else "fn") if expected[q] else ("tn" if ok else "fp")] += 1
        if not ok:
            failures.append({"query": q, "should_trigger": expected[q], "trigger_rate": round(rate, 2), "split": bucket})

    def summary(s: dict) -> dict:
        return {"pass_rate": round(s["passed"] / s["total"], 3) if s["total"] else None,
                "false_negatives": s["fn"], "false_positives": s["fp"], "queries": s["total"]}

    print(json.dumps({"train": summary(split["train"]), "test": summary(split["test"]), "failures": failures}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
