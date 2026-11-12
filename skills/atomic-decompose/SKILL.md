---
name: atomic-decompose
description: "Plans a big task as small work items, asks every scope or user-only question once with a default, then runs the items (in parallel where they touch different files) from saved state that survives compaction. Use when a task is ambiguous, has several parts, or needs research, planning or delegation, or to resume a task saved under .atomic-decompose/. Not for one edit, fact or command."
metadata:
  version: 0.2.0
  owner: pauln
---
# Atomic Decompose

You plan and ask; the script runs the work. `ad` is `python3 <dir>/scripts/decompose.py` (`<dir>` holds this file), and `<T>` is the task folder `start` prints. Every command prints JSON with a `next` field: do what it says. On `ERROR [code]`, do its `next:` line; for an exit-3 fault, see *Faults*.

## Continuing a task

After compaction, or in a new session with a folder under `<workspace>/.atomic-decompose/`, run `ad status --task <T>` and do its `next`. If there are several folders, take the newest `updated_at` in `state.json`. After compaction, also run `ad log compaction --task <T>`. If the user says this method should not have engaged, run `ad log wrong_engagement --task <T>` and carry on as normal work.

## 1. Plan

Read only what the plan needs. Then write a plan file, in a temp folder outside the workspace:

```json
{"question": "Are slugify and truncate added to textutils.py, tested and listed in README.md?",
 "requirements": ["slugify(text)", "truncate(text, width)"],
 "questions": [{"type": "scope", "text": "Should slugify keep Unicode letters?", "default": "No, ASCII only", "because": "README says ASCII"}],
 "check_cmd": "python3 -m unittest -q",
 "items": [
  {"title": "Add slugify", "covers": ["R1"], "files": ["textutils.py", "test_textutils.py", "README.md"],
   "goal": "Add slugify(text) after normalize_space: lowercase, runs of non-alphanumerics become one '-', no leading or trailing '-'. Test class Slugify: 'Hello, World!' -> 'hello-world', '' -> '', '--a--' -> 'a'. README: one line under Functions.",
   "check_cmd": "python3 -m unittest -q test_textutils.Slugify", "needs": ["Q1"]},
  {"title": "Add truncate", "covers": ["R2"], "files": ["textutils.py", "test_textutils.py", "README.md"],
   "goal": "...", "check_cmd": "python3 -m unittest -q test_textutils.Truncate"}]}
```

Rules:

- **requirements** lists each part of the request, numbered R1, R2 and so on. Every requirement needs an item that `covers` it.
- **One item, one deliverable**, with a goal precise enough that an executor needs nothing else. Look facts up and write them into the goal: names, places in the file, the exact behaviour, the edge cases.
- **`files`** lists every file an item may change (`dir/` covers a folder). Items that share a file run one after another in one executor; items with no file in common run at the same time. So when parts can be separate, give them separate files. Do not force a split: the script decides what runs at once, even when the user asks for parallel work. Use `depends: ["<id>"]` when one item needs another's result (its `id`, or its position from 1 when items have none).
- **`check_cmd`** on each writes item is the repository's own test command as one string, narrowed to the item where possible. The item's tests must include a negative case that fails if the work is wrong. `done` runs these and commits only on a pass. The top-level `check_cmd` runs over the whole task after each round.
- **A read-only item** (research, a comparison) has no `files`; give it `check`, the points you will judge its result by. Its result lands in a file under `<T>/results/`.
- **`questions`** are only what the workspace cannot answer. `scope` covers audience, depth and criteria; `user_only` covers names, budgets, owners and dates; `confirm` is a fact you found that the user should know, with the evidence as `because`. Each has the `default` you would act on. Put each question's id in the `needs` of the items it changes.
- **`skill`**: the name of an installed skill that fits the item, if one does.

Then run `ad start --root <the repository or folder the request names; file paths start there> --statement "<the request verbatim>" --plan <file>`. If it prints `plan_invalid`, fix every listed problem and rerun. Add `--mode delegate` only when the user asks for sub-agents, and `--mode main_session` when the host cannot start them.

## 2. Ask

When the action is `ask`, put every question in **one** blocking question to the user. Give each its type, its default and why, and show the plan (item titles and files) inside the prompt. Record each reply with `ad answer --id <Q> --text "<reply>" --task <T>`, or run `ad answer --defaults --task <T>` when the user accepts the defaults. Never ask again what `ad status --task <T>` shows as answered; if you did, run `ad log asked_again --ref <Q> --task <T>`. Then run `ad next --task <T>`.

## 3. Run

Do what `ad next --task <T>` prints, then run `next` again, until the action is `report`.

- **`do_yourself`:** read the brief it names and follow it yourself, item by item, calling the brief's `done` command after each item.
- **`dispatch`:** start exactly one executor per `prompt`, in the foreground and all in the same turn. Pass the prompt unchanged: it is one executor's whole job, never shared or split, even when it holds several items. Do not edit the work yourself while executors run. Run `next` only when every executor has replied.
- **`review`:** tell the user the work has landed, then start one read-only executor with its `prompt`. When it replies, run `next`. Then, for each finding worth fixing, add an item to `<T>/plan.json` and run `ad plan --task <T>`, then `next`. Name the rest in the report as gaps. With nothing to fix, run `ad finish --task <T>`.
- **`stop`:** tell the user what it names, all in one message, and wait. Never approve a step yourself. After the reply, run `ad answer` for each answer, then `ad resume --task <T>`, adding `--approve <ids>` or `--deny <ids>` exactly as the user said.

To change the plan (a discovery changes the work, or the user rescopes): edit `<T>/plan.json` and run `ad plan --task <T>`. It adds new items, edits items that have not started (drop one with `"status": "dropped"`), and keeps done ones and items the file leaves out. To record a real choice between options: `ad decide --question "<choice>" --chosen "<option>" --reject "<option>::<why it lost>" --criteria <Q-ids> --task <T>`, with `--because "<evidence>"` when no question holds the criteria. Briefs carry the decisions from then on.

## 4. Report and mark

`next` ends with `report` (or `ad finish --task <T>` prints it). If your host shows token totals, run `ad log tokens --data '{"total": N}' --task <T>` first. Then write:

1. A first sentence answering the plan's `question`.
2. The supporting points, grouped by requirement.
3. Each decision: the chosen option, and each rejected option with why it lost.
4. Each skill used, with its items.
5. Last: failed items and why, review gaps, `changed_answers` and the items they affect, `untracked_left`, the cost, and each `unconfirmed_defaults` entry for the user to confirm.

When the user accepts, run `ad mark --mark accepted --task <T>`. For rework, run `ad mark --mark reworked --reason "<reason>" --task <T>`, then edit the plan, `plan` and `next`.

## Never

- Edit, commit or revert workspace files yourself, except as an executor following a brief (`do_yourself`).
- Clear a stop without the user's reply, or approve a step for them.
- End your turn while an executor is still working.
- Quote check output in the report except from a fresh run.

## Faults

Exit code 3 means the saved state could not be read, written or locked. Stop the work and report the message and its `next`. Do not edit `state.json` or `record.jsonl` by hand. Rerun the same command once the cause is fixed: the command is safe to repeat, and `done` finds a commit it already made. For other errors, see `references/recovery.md`.
