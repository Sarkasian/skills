# Delegation

## Your host

Pass each brief unchanged as the executor's whole prompt. Run at most the lower of the task's `max_parallel` (`ad status`) and your host's cap at once.

| Host | How to start one executor | Cap |
| --- | --- | --- |
| Cursor | Task tool, one call per brief. Several calls in one message run at once. | none |
| Claude Code | Agent tool with `subagent_type` `general-purpose`. | 20 |
| Codex | Spawn one subagent per brief, giving it the brief as its task. | 6 |
| Zoo Code | `new_task` with `mode` `code`, the brief as `message`, and `todos` always passed (null, or the brief's checklist). Call it alone in its turn; the subtask's `attempt_completion` result is the reply. | 1 |
| Main session (`--mode main_session`, or no delegation) | Do the item yourself, following its brief exactly, then handle your own reply below. | 1 |

If you know before briefing that delegation is unavailable, use `ad brief <ids> --task <T> --mode main_session`. If the host refuses a brief already printed, do the item in the main session from that same brief.

## Skill paths

`add --skill` takes the absolute `SKILL.md` path of the skill as your host lists it:

- **Codex:** the `(file: <path>)` entry. If it starts with a root alias such as `r0`, replace the alias with the folder the listing's root table declares (`- r0 = <root>`).
- **Cursor:** the skill's `fullPath`. If it starts with an alias such as `$0`, replace the alias with the folder the listing declares.
- **Zoo Code:** the `<location>` entry.
- **Claude Code:** `<workspace>/.claude/skills/<name>/SKILL.md`, or else `~/.claude/skills/<name>/SKILL.md`, whichever exists. A plugin skill cannot be routed: run the item without it and name it in the result.

## Replies

Each executor ends with one line per item: `RESULT`, `BLOCKED`, `APPROVAL` or `SKILL_FAILED`, then `<id> <attempt>`. Handle each one on its own:

- **`RESULT <id> <attempt> <path>` plus a summary.**
  1. Read the result file.
  2. Judge every checklist entry against it, and check it against the settled answers and decisions in the brief.
  3. A missing file, a missing or failed entry, or a contradiction is a fail: `ad complete <id> --task <T> --attempt <n> --verdict fail --reason "<what failed>"`. The next brief carries the reason. The third failed attempt marks the item failed.
  4. If it passes and the file holds no diff: `ad complete <id> --task <T> --attempt <n> --verdict pass --result <path> --summary "<at most 150 words>"`.
  5. If it passes and the file holds a diff, see *Diffs* first.
- **`BLOCKED <id> <attempt> <question>`.**
  1. Look the fact up, as in decomposition.md, *Split*, step 3.
  2. If you find it: `complete --verdict fail --reason "<the fact>"`.
  3. If you do not: `ad ask --type user_only`, then `complete --verdict blocked --question <Q-id>`. Other ready work goes on.
- **`APPROVAL <id> <attempt> <step>`.** Leave the item running. Run `ad stop --condition needs_approval --detail "<step>"` and ask the user.
- **`SKILL_FAILED <id> <attempt> <skill>`.** Run `complete --verdict held --reason "<skill> did not load"`, then treat it as a fault.
- **No entry for an item, or a missing result path.** Run `complete --verdict fail` without `--result`. When there is no entry, take the attempt from the item's `briefs` in `ad status`.

Discard a reply whose `complete` says `not_running` or `stale_attempt`. It belongs to an older attempt.

When `complete` prints `"status": "failed"`, run `ad drop <id> --task <T> --cause <failed id>` for each id in its `dependants`, and name them with the failed item in the result.

After every pass, ask what the result changed. A discovery result or a result that contradicts the plan goes to decomposition.md, *Re-entry*. A new scope question goes to SKILL.md, *New scope question*.

## Diffs

Executors never change workspace files themselves. They put each change in the result file as a unified diff with `a/` and `b/` paths relative to the workspace root. After the checklist passes:

1. Check with `ad status` that the item is still `running` and that its `briefs` equals the reply's attempt. If not, discard the reply.
2. If the diff deletes files or changes anything outside the plan the user saw, run `ad stop --condition needs_approval` and ask first.
3. From the workspace root, run `git apply --check <result file>`, then `git apply <result file>`. If the workspace root is inside a git repository but is not its top, run both from the top with `--directory=<root's path from the top>`.
4. If the diff does not apply, nothing has changed. Run `complete --verdict fail --reason "<git's message>"`, so the retry is made against the current files. If it applies, run `complete --verdict pass`.

If `git` is missing, that is a fault.

## Approvals

When the user replies to a `needs_approval` stop, run `ad resume --task <T>`, then do one of the following:

- **A diff waiting for approval:** if approved, rerun *Diffs* steps 1, 3 and 4. If refused, run `complete --verdict fail --reason "<refusal>"`.
- **An executor's `APPROVAL`:** run `complete --verdict held --reason "<the user's approval or refusal of the step>"`. The next brief carries it.
- **A reversal:** see *Reversing*.

## Reversing

After an answer change, reverse the diff of each affected item whose `was` is `done`. Go latest first, using the order of each item's last `item_done` line in `<T>/record.jsonl`, so a later diff on the same lines comes off before the one it was applied on.

1. Run `git apply -R --check <result file>`, then `git apply -R <result file>`.
2. If a diff does not reverse cleanly, run `ad stop --condition needs_approval` and ask.
3. If the user approves, run `git apply -R --reject <result file>`. It reverses the hunks that still apply and leaves each other hunk in a `.rej` file; name those files in the result.
4. If the user refuses, leave the files unchanged and name them in the result.

Run no `complete` for a reversal.
