---
name: atomic-decompose
description: "Plans a substantial task as small work items, asks every scope or user-only question once with a default, then works to completion from saved state that survives compaction, delegating to sub-agents. Use when a task is ambiguous, has several parts, or needs research, planning or delegation, or to resume a task saved under .atomic-decompose/. Not for one edit, one fact or one command."
metadata:
  version: 0.1.0
  owner: pauln
---
# Atomic Decompose

You are the coordinator. The task's state lives in files, not in your memory: start every step from the output of a script command (`next`, `status`, or `handoff` on entry), never from what you remember.

In this file, `ad` means `python3 <dir>/scripts/decompose.py`, where `<dir>` is the absolute folder holding this `SKILL.md`. `<T>` is the task folder `init` prints. Run `ad <command> --help` for flags. On an `ERROR [code]` block, if the code is in the *Faults* table, do only what the table says; otherwise do what its `next:` line says.

## Entry: run this first, every time

- **New task** (no task folder named or found for it): engage only if the task is ambiguous, has several parts, or needs research, planning or delegation, or the user asks for this method. If the user asks you not to use it, or it is one edit, one fact or one command, do not engage.
- **Continuing** (a compaction summary, or a message continuing or resuming a task under `<workspace>/.atomic-decompose/`): take the folder the summary or user names. Otherwise, after a compaction summary, take the `active`, `stopped` or `complete` one with the latest `updated_at` in its `state.json`; in a new session, take the only such folder, and with several, list them with their governing questions and ask which. After a compaction summary run `ad log compaction --task <T>`. In a new session run `ad resume --task <T>`. Then run `ad handoff --task <T>` and follow its `Next command`. If the status is `handed_back`, stop following this method.

## 1. Start

`ad init --root <workspace> --statement "<the user's request verbatim>" --question "<one sentence the final result must answer>"`. Add `--mode main_session` when the user asks for work in this session or your host cannot delegate. If the user later says the method should not have engaged: `ad log wrong_engagement --task <T>`, then continue as normal work.

## 2. Decompose

Read `references/decomposition.md` and follow it. It ends when `ad validate --task <T>` prints `"ok": true` (an unanswered question shows as `open_question` until step 3).

## 3. Question round

Before you ask the user anything, run `ad status --task <T>`: never ask a question it shows as answered. If the user says something was already answered, run `ad log asked_again --task <T> --ref <Q-id>`.

If no question is unanswered, skip to step 4. Otherwise run `ad asked --task <T> --ids <every unanswered Q-id>` and put all of them to the user in **one** message, each labelled *scope* or *user-only*, each with its default. Then stop and wait. For each reply run `ad answer --task <T> --id <Q> --text "<answer>" --source user`, or `--source default_accepted` when the user accepts a default without answering it. Validate again.

## 4. Execute

Read `references/delegation.md` once for your host: how to delegate, your parallel cap and how to handle replies. Then loop:

1. `ad next --task <T>`. Expand or drop each group listed in `expand` first (decomposition.md, *Re-entry*).
2. If nothing is ready, nothing is running and `blocked` is not empty: `ad asked` for every open user-only question, ask them together, then `ad stop --condition blocked_on_user`. If no leaf is pending or running and `expand` is empty, go to step 5.
3. Take the first ready batches, up to the lower of `max_parallel` (in `ad status`) and your host's cap, minus the batches still running. For each run `ad brief <ids> --task <T>` and pass the printed brief **unchanged** as the whole prompt of one executor.
4. Handle each reply as it arrives, as delegation.md says, then go back to 1.

Before any stop, dispatch nothing new and first handle the replies of the batches already running.

**Choices.** When a step has more than one viable option, compare them against the settled criteria. If none covers it, state default criteria: run `ad ask --type scope` for them and then `ad answer --source default_unconfirmed`. Record the outcome with `ad decide --task <T> --item <id> --question "<choice>" --criteria <Q-ids> --chosen "<option>" --reject "<option>::<why it lost>"` (one `--reject` for each rejected option). If later items in other branches must follow it, use their nearest common ancestor as `--item`.

**Outside the plan.** Before deleting files, contacting a third party or making any change the user did not see in the plan: `ad stop --condition needs_approval --detail "<the step>"` and ask.

**New scope question** from a result: `ad ask --type scope`, `ad asked`, finish the work it does not block, then `ad stop --condition blocked_on_user --detail "<question>"`. When the answer arrives, re-expand every node that is not done (decomposition.md, *Re-entry*).

## Stops and resume

`ad stop --task <T> --condition <blocked_on_user|needs_approval|fault|user_stop> --detail "<what is needed>"`. Then tell the user which condition you stopped on and what you need to continue. When they answer, approve or say continue, record any answers and run `ad resume --task <T>`, then `ad handoff --task <T>`. To handle an approval, see delegation.md, *Approvals*.

## Changed answer

The user changes a settled answer: run `ad answer` with the new text. It prints `affected`, with each item's previous status in `was`.

- Discard a reply from a brief sent before the change: `complete` rejects it with `not_running` or `stale_attempt`, and delegation.md *Diffs* step 1 catches it before a diff is applied.
- For items whose `was` is `done`, reverse their diffs latest first (delegation.md, *Reversing*).
- For items whose `was` is `failed`, re-add the items they caused to be dropped (decomposition.md, *Re-entry*).
- Continue with step 4.

The result must name the affected items: in `ad status`, the items whose `needs` hold a question with a non-null `changed_at`.

## 5. Result and mark

Run `ad finish --task <T>`, then `ad status --task <T>`, and write the result:

1. The first sentence answers the governing question.
2. Supporting points follow, grouped under the top-level items.
3. Each decision: the chosen option, each rejected option and why it lost.
4. Each skill used, with its items, and any matching skill you could not route.
5. Last: the failed and dropped items, the items a changed answer affected (as in *Changed answer*), and every `default_unconfirmed` answer, asking the user to confirm each.

If the user accepts, run `ad mark --task <T> --mark accepted`. If they ask for rework, run `ad mark --task <T> --mark reworked --reason "<their reason>"`, re-plan from the reason (`add`, `drop`, `validate`) and continue step 4 with the same settled answers. If they do neither, write nothing.

When your host shows you its token totals, run `ad log tokens --task <T> --data '{"total": N, "before_first_item": N, "available": true}'` at `finish` and at every stop. Otherwise pass `{"available": false}`.

## Show the plan

Whenever asked: `ad status --task <T>`, then show the governing question, each item with its status, and the settled answers.

## Faults

A command that exits 3 is a fault. Stop the work and report the error's message and its `next` step. Then run only:

| Error | Do |
| --- | --- |
| `state_write_failed` | Nothing more. `resume` re-applies the change later. |
| `state_unreadable` | Nothing more. Report the cause. |
| `record_write_failed` | `ad stop --condition fault` once. If it reports `record_torn`, run `ad resume` first. |
| `record_torn` | `ad resume`, then rerun the failed command only if `resume`'s `applied` list lacks it. Report `torn_line`, then carry on; no stop. |
| `task_locked` | Nothing more. Name the lock file; the user deletes it only when no other session is working on the task. |
| `git` missing, `skill_missing`, a `SKILL_FAILED` reply | `ad stop --condition fault`, naming the cause. |
