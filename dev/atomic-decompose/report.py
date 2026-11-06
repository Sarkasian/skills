#!/usr/bin/env python3
"""C-8 report script (TDD API-12): scores the release evaluation and rolls run records up into weekly metrics.

  python3 report.py release --runs evals/runs [--cursor-export <csv>]
  python3 report.py weekly --roots <harness>=<dir>... --week <YYYY-Www> --marks <weekly folder>

Standard library only. Exit codes: 0 written, 2 bad input (`bad_run_line`, `case_mismatch`, `marks_unreadable`).

Scope for now (pauln, 2026-11-06): Cursor only. Host token parsing waits for an export of pauln's account to pin
the Cursor usage-export columns (PRD §12), so every token total is null and the values that need one are
`not_computable`; `--cursor-export` is accepted and not read. `score_trigger_evals.py` is not run (NFR-4 and NFR-9
are computed here); M-6 and M-9 are `unmeasured` for any non-Cursor harness given to `weekly`.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
from pathlib import Path

TASK_TARGETS = {"with": "NFR-1 NFR-2 NFR-3 NFR-5 NFR-6 NFR-7 NFR-10 NFR-11 exit criterion 2",
                "without": "NFR-2 NFR-3 exit criterion 2", "main_session": "NFR-11"}


class Fail(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def ts(s):
    return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def held_out(query):
    return int(hashlib.sha256(query.encode()).hexdigest(), 16) % 10 >= 6


def read_record(task_dir):
    """DM-5 lines of a task folder, and whether a line does not parse (a torn record)."""
    lines, torn = [], False
    try:
        raw = (Path(task_dir) / "record.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], True
    for text in raw:
        if not text.strip():
            continue
        try:
            lines.append(json.loads(text))
        except json.JSONDecodeError:
            torn = True
    return lines, torn


def reasked(lines, in_window=lambda line: True):
    """[NFR-5, M-1] Distinct question ids asked again: an asked_again event, or a question_asked for a question
    already answered from a source other than default_unconfirmed."""
    settled, ids = set(), set()
    for line in lines:
        ref, ev = line.get("ref"), line.get("event")
        if ev == "answered" and (line.get("data") or {}).get("source") != "default_unconfirmed":
            settled.add(ref)
        elif in_window(line) and (ev == "asked_again" or (ev == "question_asked" and ref in settled)):
            ids.add(ref)
    return ids


def rate(met, total):
    return round(met / total, 3) if total else None


# ---------------------------------------------------------------- release

def load_cases(evals_dir):
    tasks = {c["id"]: c for c in json.loads((evals_dir / "evals.json").read_text(encoding="utf-8"))["evals"]}
    for c in tasks.values():
        if {p["fact"] for p in c["planted_questions"]} != {s["fact"] for s in c["scripted_answers"]}:
            raise Fail("case_mismatch", f"evals.json case {c['id']}: scripted_answers and planted_questions "
                                        "name different facts")
    engage = {c["query"]: c for c in json.loads((evals_dir / "trigger_evals.json").read_text(encoding="utf-8"))}
    return tasks, engage


def load_runs(runs_dir, tasks, engage):
    runs = {}
    for path in sorted(runs_dir.glob("*/runs.jsonl")):
        for n, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not text.strip():
                continue
            try:
                r = json.loads(text)
                kind, _, key = r["case"].partition(":")
                case = tasks[int(key)] if kind == "task" else engage[key] if kind == "engage" else None
                if case is None or r["attempt"] not in (1, 2):
                    raise ValueError(r["case"])
                r["_case"], r["_kind"] = case, kind
                r["_dir"] = path.parent
            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
                raise Fail("bad_run_line", f"{path}:{n}: {e!r}")
            runs.setdefault((r["harness"], r["case"], r["arm"]), []).append(r)
    return runs


def select(attempts):
    """[US-12.7, US-12.10] The scored attempt: attempt 2 when one exists, else attempt 1."""
    r = max(attempts, key=lambda a: a["attempt"])
    r["_interrupted"] = r["interrupted"] != "none"
    r["_met"] = [bool(e["met"]) and not r["_interrupted"] for e in r["expectations"]]
    r["_pass"] = bool(r["_met"]) and all(r["_met"])
    if r["_kind"] == "engage":
        r["_triggered"] = (not r["_case"]["should_trigger"]) if r["_interrupted"] else bool(r["triggered"])
    return r


def target(out, tid, harness, value, goal, met):
    out.append({"id": tid, "harness": harness, "value": value, "target": goal,
                "met": bool(met) and value != "not_computable"})


def cmd_release(a):
    runs_dir = Path(a.runs)
    tasks, engage = load_cases(runs_dir.parent)
    runs = {k: select(v) for k, v in load_runs(runs_dir, tasks, engage).items()}
    sel = list(runs.values())
    harnesses = sorted({r["harness"] for r in sel})

    def task_runs(h, arm):
        return [r for r in sel if r["harness"] == h and r["arm"] == arm and r["_kind"] == "task"]

    def pooled(rs):
        return rate(sum(sum(r["_met"]) for r in rs), sum(len(r["_met"]) for r in rs))

    targets = []
    cur_with, cur_without = task_runs("cursor", "with"), task_runs("cursor", "without")
    nfr1 = pooled(cur_with)
    target(targets, "NFR-1", "cursor", nfr1 if nfr1 is not None else "not_computable", ">= 0.9",
           nfr1 is not None and nfr1 >= 0.9)
    same = ({r["case"] for r in cur_with} == {r["case"] for r in cur_without}
            and len({r["model"] for r in cur_with + cur_without}) == 1)
    nfr2 = round(nfr1 - pooled(cur_without), 3) if same and cur_with else "not_computable"
    target(targets, "NFR-2", "cursor", nfr2, ">= +0.20", nfr2 != "not_computable" and nfr2 >= 0.2)
    met_with, met_without = (sum(sum(r["_met"]) for r in rs) for rs in (cur_with, cur_without))
    # NFR-3 is decided without tokens when either arm meets no expectation; otherwise it needs the token totals.
    if cur_without and met_without == 0:
        target(targets, "NFR-3", "cursor", None, "<= 1.0 of the without ratio", True)
    elif cur_without and met_with == 0:
        target(targets, "NFR-3", "cursor", None, "<= 1.0 of the without ratio", False)
    else:
        target(targets, "NFR-3", "cursor", "not_computable", "<= 1.0 of the without ratio", False)
    main = pooled(task_runs("cursor", "main_session"))
    nfr11 = main if main is not None and nfr1 is not None else "not_computable"
    target(targets, "NFR-11", "cursor", nfr11, ">= NFR-1 - 0.10", nfr11 != "not_computable" and main >= nfr1 - 0.1)

    for h in harnesses:
        engaged = [r for r in sel if r["harness"] == h and r["_kind"] == "engage" and held_out(r["_case"]["query"])]
        for tid, should in (("NFR-4", True), ("NFR-9", False)):
            pool = [r for r in engaged if r["_case"]["should_trigger"] is should]
            v = rate(sum(r["_triggered"] is should for r in pool), len(pool))
            target(targets, tid, h, v if v is not None else "not_computable", ">= 0.9", v is not None and v >= 0.9)
        with_runs = task_runs(h, "with")
        long_runs = [r for r in with_runs if "long_run" in r["_case"]["covers"]]
        if long_runs:
            v = sum(len(r["_met"]) - sum(r["_met"]) for r in long_runs)
            v += sum(len(reasked(read_record(r["_dir"] / r["task_dir"])[0])) for r in long_runs if r["task_dir"])
            target(targets, "NFR-5", h, v, "0", v == 0 and not any(r["_interrupted"] for r in long_runs))
        else:
            target(targets, "NFR-5", h, "not_computable", "0", False)
        planted = sum(len(r["_case"]["planted_questions"]) for r in with_runs)
        asked = sum(len({p["fact"] for p in r["planted_asked"] if p["in_round"]}) for r in with_runs)
        v = rate(asked, planted)
        target(targets, "NFR-6", h, v if v is not None else "not_computable", "1.0",
               v == 1 and not any(r["_interrupted"] for r in with_runs))
        if h != "cursor":
            v = pooled(with_runs)
            ok = v is not None and nfr1 is not None
            target(targets, "NFR-7", h, v if ok else "not_computable", ">= NFR-1 - 0.10", ok and v >= nfr1 - 0.1)
        try:
            load = json.loads((runs_dir / h / "load_tokens.json").read_text(encoding="utf-8"))["tokens"]
        except (OSError, json.JSONDecodeError, KeyError):
            load = "not_computable"
        target(targets, "NFR-8", h, load, "<= 5000", load != "not_computable" and load <= 5000)
        disc = [r["discoverable_asked"] for r in with_runs]
        v = sum(disc) if with_runs and None not in disc else "not_computable"
        target(targets, "NFR-10", h, v, "0", v == 0 and not any(r["_interrupted"] for r in with_runs))

    ec2_harnesses = [h for h in harnesses if h != "zoo_code_local"]
    passes = {arm: sum(r["_pass"] for h in ec2_harnesses for r in task_runs(h, arm)) for arm in ("with", "without")}
    missing = []
    for h in ec2_harnesses:
        missing.append({"harness": h, "lacks": "tokens"})
        if not all(r["subagent_attribution_verified"] for r in task_runs(h, "with") + task_runs(h, "without")):
            missing.append({"harness": h, "lacks": "attribution"})
    if passes["without"] == 0:
        ec2 = "not_met"
    elif passes["with"] == 0:
        ec2 = "met"
    else:
        ec2 = "not_computable"
    nfr3 = next(t for t in targets if t["id"] == "NFR-3")

    base = runs.get(("cursor", "task:1", "delegate_baseline"))
    case1 = runs.get(("cursor", "task:1", "with"))
    report = {
        "targets": targets,
        "gate": "pass" if all(t["met"] for t in targets) else "fail",
        "exit_criterion_2": ec2,
        "exit_criterion_2_missing": missing if ec2 == "not_computable" else [],
        "tokens": [{"harness": r["harness"], "model": r["model"], "case": r["case"], "arm": r["arm"],
                    "total": None, "estimate": False} for r in sel if r["_kind"] == "task"],
        "criterion_10_runs": [{"harness": r["harness"], "arm": r["arm"], "case": r["case"]}
                              for r in sel if r["_interrupted"]],
        "delegate_baseline": None if base is None else {
            "total": None, "expectations_met": sum(base["_met"]),
            "with_total": None, "with_expectations_met": sum(case1["_met"]) if case1 else None},
        "pr6": {"half_up": ec2, "half_down": ec2, "changed": False,
                "escalate": nfr3["value"] == "not_computable"},
    }
    for h in harnesses:
        with open(runs_dir / h / "trigger_runs.jsonl", "w", encoding="utf-8") as f:
            for r in sel:
                if r["harness"] == h and r["_kind"] == "engage":
                    f.write(json.dumps({"query": r["_case"]["query"], "should_trigger": r["_case"]["should_trigger"],
                                        "triggered": r["_triggered"]}) + "\n")
    faults = [r for v in load_runs(runs_dir, tasks, engage).values() for r in v
              if r["attempt"] == 1 and r["interrupted"] != "none"]
    (runs_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (runs_dir / "report.md").write_text(render_md(report, sel, faults), encoding="utf-8")
    print(json.dumps({"gate": report["gate"], "exit_criterion_2": ec2, "report": str(runs_dir / "report.md")}))
    return 0


def render_md(rep, sel, faults):
    failed = [f"{t['id']} ({t['harness']})" for t in rep["targets"] if not t["met"]]
    out = ["# Release evaluation report", ""]
    out.append(f"**Release gate failed.** Failed targets: {', '.join(failed)}." if failed
               else "**Release gate passed.** Every PRD §5 target is met.")
    ec2 = {"met": "Charter §11 exit criterion 2 is **met**: the project halts (charter Risk-1).",
           "not_met": "Charter §11 exit criterion 2 is not met: the with-method ratio is not exceeded.",
           "not_computable": "Charter §11 exit criterion 2 could not be checked; the go / no-go decision goes to "
                             "the sponsor (charter Risk-1). Lacking: " + ", ".join(
                                 f"{m['harness']} {m['lacks']}" for m in rep["exit_criterion_2_missing"]) + "."}
    out += ["", ec2[rep["exit_criterion_2"]]]
    if rep["pr6"]["escalate"]:
        out.append("NFR-3 could not be computed on Cursor: treated as failed and escalated to the sponsor (PRD PR-6).")
    weak = [r for r in sel if r["_kind"] == "task" and r["arm"] == "with" and r["_case"].get("weak_result")]
    if any(not r["_pass"] for r in weak):
        out.append("A case with a planted weak result failed the acceptance check with the method: "
                   "escalate the gate to the sponsor (PRD PR-4).")
    out += ["", "| Target | Harness | Value | Target | Met |", "| --- | --- | --- | --- | --- |"]
    out += [f"| {t['id']} | {t['harness']} | {t['value']} | {t['target']} | {'yes' if t['met'] else 'no'} |"
            for t in rep["targets"]]
    out += ["", "## Models", ""]
    out += [f"- {h}: {', '.join(sorted({r['model'] for r in sel if r['harness'] == h}))}"
            for h in sorted({r["harness"] for r in sel})]
    out += ["", "## Tokens", "", "Not computed: Cursor token parsing waits for the usage-export columns (PRD §12)."]
    if rep["delegate_baseline"]:
        b = rep["delegate_baseline"]
        out.append(f"DD-9 delegation baseline, case 1: {b['expectations_met']} expectations met, against "
                   f"{b['with_expectations_met']} for case 1's `with` run (in no target).")
    if rep["criterion_10_runs"]:
        out += ["", "## Runs scored as failed (US-12 criterion 10)", ""]
        out += [f"- {r['harness']} {r['arm']} {r['case']}: affects "
                f"{'NFR-4 NFR-9' if r['case'].startswith('engage:') else TASK_TARGETS.get(r['arm'], 'none')}"
                for r in rep["criterion_10_runs"]]
    if faults:
        out += ["", "## Evaluation-setup faults (US-12 criterion 7)", ""]
        out += [f"- {r['harness']} {r['arm']} {r['case']}: attempt 1 {r['interrupted']}" for r in faults]
    out += ["", "## Expectations", ""]
    for r in sorted(sel, key=lambda r: (r["harness"], r["case"], r["arm"])):
        if r["_kind"] == "task":
            out.append(f"### {r['harness']} {r['arm']} {r['case']} (attempt {r['attempt']})")
            out += [f"- {'pass' if m else 'FAIL'}: {e['text']}" for e, m in zip(r["expectations"], r["_met"])]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- weekly

def read_marks(path):
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    except json.JSONDecodeError as e:
        raise Fail("marks_unreadable", f"{path}: not valid JSON ({e})")
    for field, kind in (("schema_version", int), ("week", str), ("sessions", list), ("questions", list)):
        if not isinstance(m.get(field), kind):
            raise Fail("marks_unreadable", f"{path}: field {field}")
    if m["schema_version"] != 1:
        raise Fail("marks_unreadable", f"{path}: field schema_version")
    return m


def cmd_weekly(a):
    year, _, wk = a.week.partition("-W")
    try:
        start = _dt.datetime.combine(_dt.date.fromisocalendar(int(year), int(wk), 1), _dt.time(), _dt.timezone.utc)
    except ValueError:
        raise Fail("bad_input", f"--week {a.week}: expected YYYY-Www")
    end = start + _dt.timedelta(days=7)

    def in_week(line):
        return start <= ts(line["ts"]) < end

    tasks, gaps, harnesses = [], [], []
    for spec in a.roots:
        harness, _, root = spec.partition("=")
        harnesses.append(harness)
        if not Path(root).is_dir():
            raise Fail("bad_input", f"--roots {spec}: not a folder")
        for d in sorted(p for p in Path(root).iterdir() if p.is_dir()):
            lines, torn = read_record(d)
            if not any(in_week(l) for l in lines if "ts" in l):
                continue
            try:
                st = json.loads((d / "state.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                st = None
            if torn or st is None:
                gaps.append(str(d))
            else:
                tasks.append((os.path.realpath(d), st, lines))
    base = "incomplete" if len(gaps) * 10 > len(tasks) + len(gaps) else "measured"
    marks = read_marks(Path(a.marks) / f"{a.week}-marks.json")
    metrics = []

    def metric(mid, value, status=None, harness=None):
        if status is None:
            status = base if value is not None else "incomplete"
        metrics.append({"id": mid, "harness": harness, "value": value, "status": status})

    week_lines = [(d, l) for d, _, lines in tasks for l in lines if in_week(l)]
    if marks is None:
        metric("M-1", None, "unmeasured")
        metric("M-2", None, "unmeasured")
    else:
        dirs = {d for d, _, _ in tasks}
        contradictions = sum(s.get("contradictions") or 0 for s in marks["sessions"]
                             if s.get("task_dir") and os.path.realpath(s["task_dir"]) in dirs)
        metric("M-1", sum(len(reasked(lines, in_week)) for _, _, lines in tasks) + contradictions)
        cls = {(os.path.realpath(q["task_dir"]), q["ref"]): q.get("discoverable") for q in marks["questions"]}
        asked = {(d, l["ref"]) for d, l in week_lines if l["event"] == "question_asked"}
        marked = [cls[k] for k in asked if cls.get(k) is not None]
        metric("M-2", rate(sum(marked), len(marked)))

    ended = []
    for _, st, lines in tasks:
        stops = [l for l in lines if l["event"] == "stopped"]
        if (st["status"] in ("stopped", "complete") and stops and in_week(stops[-1])
                and not any(l["event"] == "wrong_engagement" for l in lines)
                and stops[-1]["data"].get("condition") != "user_stop"):
            ended.append(stops[-1]["data"].get("condition"))
    metric("M-3", rate(sum(c != "complete" for c in ended), len(ended)))
    done = {(d, l["ref"]) for d, l in week_lines if l["event"] == "item_done"}
    failed = {(d, l["ref"]) for d, l in week_lines if l["event"] == "item_failed"}
    metric("M-4", rate(len(failed), len(done | failed)))
    engaged = [lines for _, _, lines in tasks if any(l["event"] == "engaged" and in_week(l) for l in lines)]
    metric("M-5", rate(sum(any(l["event"] == "wrong_engagement" for l in ls) for ls in engaged), len(engaged)))
    marks_m7 = [l["data"].get("mark") for _, l in week_lines if l["event"] == "marked"]
    v = rate(marks_m7.count("reworked"), len(marks_m7))
    metric("M-7", v, None if len(marks_m7) >= 5 else "incomplete")
    rounds = []
    for d, st, lines in tasks:
        asked = {l["ref"] for l in lines if l["event"] == "question_asked" and in_week(l)}
        by_round = {}
        for q in st.get("questions", []):
            if q.get("round") is not None:
                by_round.setdefault(q["round"], []).append(q)
        for qs in by_round.values():
            if any(q["id"] in asked for q in qs) and all(q.get("answer_source") for q in qs):
                rounds.append(all(q["answer_source"] == "default_accepted" for q in qs))
    metric("M-8", rate(sum(rounds), len(rounds)))
    for h in sorted(set(harnesses) - {"cursor"}):
        metric("M-6", None, "unmeasured", h)
        metric("M-9", None, "unmeasured", h)

    out = {"week": a.week, "metrics": metrics, "gaps": gaps}
    (Path(a.marks) / f"{a.week}.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("release")
    r.add_argument("--runs", required=True)
    r.add_argument("--cursor-export")
    w = sub.add_parser("weekly")
    w.add_argument("--roots", nargs="+", required=True)
    w.add_argument("--week", required=True)
    w.add_argument("--marks", required=True)
    a = ap.parse_args(argv)
    try:
        return cmd_release(a) if a.command == "release" else cmd_weekly(a)
    except Fail as e:
        print(f"ERROR [{e.code}] {e.message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
