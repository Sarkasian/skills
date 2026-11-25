---
name: atomic-decompose
description: "Plans a big task as small work items, asks every scope or user-only question once with a default, then runs the items (in parallel where they touch different files) from saved state that survives compaction. Use when a task is ambiguous, has several parts, or needs research, planning or delegation, or to resume a task saved under .atomic-decompose/. Not for one edit, fact or command."
license: MIT
metadata:
  version: 0.3.0
  composes_with:
    - skill: deep-research-run
      when: item type is research
      role: executor
---
# Atomic Decompose

You plan and ask; the script runs the work. `ad` is `python3 <dir>/scripts/decompose.py` (`<dir>` holds this file), and `<T>` is the task folder `start` prints. Every command prints JSON with a `next` field: do what it says. On `ERROR [code]`, do its `next:` line; if that is not enough, read that code's section in `references/recovery.md`. `ad --help` lists every command.

## Continuing a task

After compaction, or in a new session with a folder under `<workspace>/.atomic-decompose/`, run `ad status --task <T>` and do its `next`. With several folders, take the newest `updated_at` in `state.json`. Never ask the user again what `status` shows as answered. If the user says this method should not have engaged, run `ad log wrong_engagement --task <T>`.

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

- **`requirements`**: each part of the request, numbered R1, R2 and so on. Every one needs an item that `covers` it.
- **One item, one deliverable.** Its `goal` is all the executor gets, so look the facts up and write them in: names, places in the file, the exact behaviour, the edge cases.
- **`files`**: every file the item may change (`dir/` covers a folder). Items sharing a file run in order; separate files run in parallel. Don't force a split — the script handles it. `depends: ["<id>"]` makes an item wait for another's result.
- **`check_cmd`**, on every item with `files`: the repository's own test command, narrowed to the item where possible. Must include a negative case that fails if the work is wrong.
- **A read-only item** (research, a comparison) has no `files`. Give it `check`: the points you will judge its result by.
- **`questions`**: only what the workspace cannot answer, each with the `default` you would act on. `scope` is audience, depth and criteria; `user_only` is names, budgets, owners and dates; `confirm` is a fact you found that the user should know, with the evidence as `because`. Put each question's id in the `needs` of the items it changes.
- **`skill`**: the name of an installed skill that fits the item, if one does.

Then run `ad start --root <the repository or folder the request names; file paths start there> --statement "<the request verbatim>" --plan <file>`. Add `--mode delegate` only when the user asks you to delegate the work, `--mode main_session` when the host cannot start executors, and `--max-parallel <N>` when the user says how many may work at once.

## 2. Run

`start` prints the first action, and `ad next --task <T>` prints each one after it. Do what each action's `next` says, until the action is `report`. Three commands are yours to run unprompted:

- **The work changes** (a discovery, or the user rescopes): edit `<T>/plan.json`, then run `ad plan --task <T>`. It adds new items and edits items that have not started. To drop one, give it `"status": "dropped"`.
- **A real choice between options**: `ad decide --question "<choice>" --chosen "<option>" --reject "<option>::<why it lost>" --criteria <Q-ids> --task <T>`, with `--because "<evidence>"` when no question holds the criteria.
- **New direction for an item not yet finished**: `ad annotate --item <id> --note "<direction>" --task <T>`. Its next brief carries the note. A running item reads it only on a retry.

## 3. Report

When the action is `report`, write:

1. A first sentence answering the plan's `question`.
2. The supporting points, grouped by requirement.
3. Each decision: the chosen option, and each rejected option with why it lost.
4. Each skill used, with its items.
5. Last: failed items and why, review gaps, `changed_answers` and the items they affect, `untracked_left`, the cost, and each `unconfirmed_defaults` entry for the user to confirm.

When the user accepts, run `ad mark --mark accepted --task <T>`. For rework, run `ad mark --mark reworked --reason "<reason>" --task <T>` and do its `next`.

## Never

- Edit workspace files yourself, except as an executor following a brief (`do_yourself`).
- Clear a stop without the user's reply.
- End your turn while an executor is still working.
- Quote check output in the report except from a fresh run.
- Edit `state.json` or `record.jsonl` by hand.
