"""The plan file: reading it, checking it and applying it to the items."""
from __future__ import annotations

import json
import os
import sys

from ad.common import Fail, QUESTION_TYPES, TASK_DIR


def _list(value):
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def _norm_path(p):
    p = str(p).replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p


def read_plan_file(path):
    try:
        text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
        plan = json.loads(text)
    except OSError as e:
        raise Fail("plan_unreadable", f"cannot read {path}: {e}", 2)
    except ValueError as e:
        raise Fail("plan_invalid", f"{path} is not JSON: {e}", 2, "needs_fix", "fix the JSON and rerun")
    if not isinstance(plan, dict):
        raise Fail("plan_invalid", "the plan must be one JSON object", 2)
    return plan


def plan_items(plan):
    items = plan.get("items") or []
    if isinstance(items, dict):  # accept {"1": {...}} as well as a list
        items = [dict(v, id=v.get("id", k)) if isinstance(v, dict) else v for k, v in items.items()]
    return items


def normalise_item(raw):
    if not isinstance(raw, dict):
        return None
    return {"id": str(raw["id"]) if raw.get("id") is not None else None,
            "title": str(raw.get("title") or "").strip(), "goal": str(raw.get("goal") or "").strip(),
            "covers": [str(c) for c in _list(raw.get("covers"))],
            "files": [_norm_path(f) for f in _list(raw.get("files"))],
            "check_cmd": [str(c) for c in _list(raw.get("check_cmd"))],
            "check": [str(c) for c in _list(raw.get("check"))],
            "needs": [str(q) for q in _list(raw.get("needs"))],
            "depends": [str(d) for d in _list(raw.get("depends"))],
            "skill": raw.get("skill") or None}


def plan_problems(st):
    """Every problem in the plan at once, so one fix round clears them all."""
    probs = []
    if not st["question"]:
        probs.append("`question`: one sentence the result must answer")
    if not st["requirements"]:
        probs.append("`requirements`: list each part of the request")
    qids = {q["id"] for q in st["questions"]}
    for q in st["questions"]:
        if q["type"] not in QUESTION_TYPES:
            probs.append(f"{q['id']}: `type` must be one of {', '.join(QUESTION_TYPES)}")
        if not q["text"] or (not q["default"] and q.get("origin") != "block"):
            probs.append(f"{q['id']}: needs `text` and a `default`")
    live = [it for it in st["items"] if it["status"] != "dropped"]
    if not live:
        probs.append("`items`: the plan has no items")
    ids, titles = {it["id"] for it in st["items"]}, {}
    reqs = {f"R{i + 1}" for i in range(len(st["requirements"]))}
    covered = set()
    for it in live:
        name = f"item {it['id']} ({it['title'] or 'no title'})"
        if not it["title"]:
            probs.append(f"{name}: needs a `title`")
        elif it["title"] in titles:
            probs.append(f"{name}: title also used by item {titles[it['title']]}")
        titles.setdefault(it["title"], it["id"])
        if not it["goal"]:
            probs.append(f"{name}: needs a `goal`")
        if it["files"] and not it["check_cmd"]:
            probs.append(f"{name}: an item with `files` needs `check_cmd` (the repository's own test command)")
        if not it["files"] and not (it["check"] or it["check_cmd"]):
            probs.append(f"{name}: a read-only item needs `check` (points to judge its result by)")
        for f in it["files"]:
            if not f or os.path.isabs(f) or f == ".." or f.startswith("../") or "/../" in f \
                    or f.split("/")[0] in (TASK_DIR, ".git"):
                probs.append(f"{name}: file {f!r} must be a path inside the root, not under .git/ or {TASK_DIR}/")
        for c in it["covers"]:
            if c not in reqs:
                probs.append(f"{name}: covers {c}, but requirements are {', '.join(sorted(reqs)) or 'none'}")
        covered.update(it["covers"])
        for q in it["needs"]:
            if q not in qids:
                probs.append(f"{name}: needs {q}, which is not a question")
        for d in it["depends"]:
            if d not in ids or d == it["id"]:
                probs.append(f"{name}: depends on {d}, which is not another item")
    for r in sorted(reqs - covered, key=lambda r: int(r[1:])):
        probs.append(f"{r} ({st['requirements'][int(r[1:]) - 1]}): no item `covers` it")
    if _cycle(st):
        probs.append(f"`depends` has a cycle: {' -> '.join(_cycle(st))}")
    # ponytail: sees a split command only by its flag, so ["npm", "test"] passes; upgrade: `command -v` first words.
    if any(c.lstrip().startswith("-") for x in [st] + live for c in x["check_cmd"]):
        probs.append('`check_cmd`: write each command whole in one string ("python3 -m unittest -q"), not as words')
    return probs


def _cycle(st):
    deps = {it["id"]: it["depends"] for it in st["items"] if it["status"] != "dropped"}
    seen, stack = set(), []

    def visit(i):
        if i in stack:
            return stack[stack.index(i):] + [i]
        if i in seen or i not in deps:
            return None
        seen.add(i)
        stack.append(i)
        for d in deps[i]:
            c = visit(d)
            if c:
                return c
        stack.pop()
        return None

    for i in deps:
        c = visit(i)
        if c:
            return c
    return None


def apply_plan(st, plan, task):
    """Merge a plan file into the state: new items are added; items not started are edited, or dropped by
    `"status": "dropped"`. Items the file leaves out are kept as they are."""
    out = {"added": [], "edited": [], "dropped": [], "kept": []}
    if "question" in plan:
        st["question"] = str(plan["question"] or "").strip()
    if "requirements" in plan:
        st["requirements"] = [str(r) for r in _list(plan["requirements"])]
    if "check_cmd" in plan:
        st["check_cmd"] = [str(c) for c in _list(plan["check_cmd"])]
    by_q = {q["id"]: q for q in st["questions"]}
    for raw in _list(plan.get("questions")):
        if not isinstance(raw, dict):
            continue
        q = by_q.get(str(raw.get("id"))) if raw.get("id") else None
        if q is None:
            q = {"id": f"Q{len(st['questions']) + 1}", "asked": False, "answer": None, "answer_source": None,
                 "changed_at": None, "affected": [], "origin": "plan"}
            st["questions"].append(q)
        if q["answer"] is None:
            q.update(type=str(raw.get("type") or "scope"), text=str(raw.get("text") or ""),
                     default=str(raw.get("default") or ""), because=raw.get("because"))
    by_id = {it["id"]: it for it in st["items"]}
    alias, touched = {}, []
    open_states = ("pending", "failed", "blocked")
    for raw in plan_items(plan):
        new = normalise_item(raw)
        if new is None:
            continue
        old = by_id.get(new["id"]) if new["id"] else None
        if raw.get("status") == "dropped":
            if old is not None and old["status"] in open_states:
                old["status"] = "dropped"
                out["dropped"].append(old["id"])
            continue
        if old is None:
            given, new["id"] = new["id"], str(max([int(i["id"]) for i in st["items"]] + [0]) + 1)
            if given:
                alias[given] = new["id"]
            new.update(status="pending", tries=0, notes=[], commit=None, result=None, block=None, run=None,
                       failure=None, origin="plan")
            st["items"].append(new)
            by_id[new["id"]] = new
            out["added"].append(new["id"])
        elif old["status"] in open_states:
            fields = {k: new[k] for k in ("title", "goal", "covers", "files", "check_cmd", "check", "needs",
                                          "depends", "skill")}
            # Compare like with like: the item as a plan file gives it. `block --question` adds its question to the
            # item's needs in the state alone, so that need is no edit; a real edit withdraws the question.
            asked, was = (old["block"] or {}).get("question"), normalise_item(old)
            was["needs"], fields["needs"] = ([n for n in ns if n != asked] for ns in (was["needs"], fields["needs"]))
            if any(was[k] != v for k, v in fields.items()) or (old["status"] != "pending"
                                                                and raw.get("status") == "pending"):
                old.update(fields, status="pending", block=None, failure=None, tries=0)
                out["edited"].append(old["id"])
        else:
            out["kept"].append(old["id"])
        touched.append(by_id[new["id"]])
    for it in touched:  # `depends` may name the plan file's own ids for new items
        it["depends"] = [alias.get(d, d) for d in it["depends"]]
    probs = plan_problems(st)
    if probs:
        raise Fail("plan_invalid", f"{len(probs)} problem(s) in the plan:\n- " + "\n- ".join(probs), 2,
                   "needs_fix", "fix every listed problem in the plan file, then rerun the same command")
    write_plan_file(task, st)
    return out


def write_plan_file(task, st):
    """The task's own plan.json, with ids, is the file to edit for `plan`. Its items carry no status: in a plan
    file `status` is only ever an instruction (`"dropped"` drops an open item, `"pending"` retries a failed or
    blocked one), and a status written here would be read back as one. The `status` command shows the statuses."""
    plan = {"question": st["question"], "requirements": st["requirements"], "check_cmd": st["check_cmd"],
            "questions": [{k: q[k] for k in ("id", "type", "text", "default", "because")} for q in st["questions"]],
            "items": [{k: it[k] for k in ("id", "title", "goal", "covers", "files", "check_cmd", "check",
                                          "needs", "depends", "skill")}
                      for it in st["items"] if it["status"] != "dropped"]}
    with open(task.plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
