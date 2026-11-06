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

To start items early (SKILL.md step 3), run each executor in the background, for example with the Cursor Task tool's background option, and ask the questions with the host's blocking question tool. Collect each background reply once the user has answered.

## Skill paths

`add --skill` takes the absolute `SKILL.md` path of the skill as your host lists it:

- **Codex:** the `(file: <path>)` entry. If it starts with a root alias such as `r0`, replace the alias with the folder the listing's root table declares (`- r0 = <root>`).
- **Cursor:** the skill's `fullPath`. If it starts with an alias such as `$0`, replace the alias with the folder the listing declares.
- **Zoo Code:** the `<location>` entry.
- **Claude Code:** `<workspace>/.claude/skills/<name>/SKILL.md`, or else `~/.claude/skills/<name>/SKILL.md`, whichever exists. A plugin skill cannot be routed: run the item without it and name it in the result.

## Replies

Each executor ends with one line per item: `RESULT`, `BLOCKED`, `APPROVAL` or `SKILL_FAILED`, then `<id> <attempt>`. Handle each one on its own:

- **`RESULT <id> <attempt> <path>` plus a summary and `CHECK` lines.**
  1. In `ad status`, the item must still be `running` with `briefs` equal to `<attempt>`; otherwise discard the reply.
  2. If the item has command entries, run `ad verify <id> --task <T>`. If it exits 1, run the `complete --verdict fail` its `next` line gives.
  3. For each judgement entry, read the lines its `CHECK <id> <n> <path>:<line>` pointer names. Read the result file only when a pointer is missing or in doubt. Check the result against the settled answers and decisions in the brief.
  4. A missing file, a missing or failed entry, or a contradiction is a fail: `ad complete <id> --task <T> --attempt <n> --verdict fail --reason "<what failed>"`. The next brief carries the reason. The third failed attempt marks the item failed.
  5. If it passes and the item has no `writes` (`ad status`): `ad complete <id> --task <T> --attempt <n> --verdict pass --result <path> --summary "<at most 150 words>"`.
  6. If it passes and the item has `writes`, see *Workspace changes* first.
- **`BLOCKED <id> <attempt> <question>`.**
  1. Look the fact up, as in decomposition.md, *Split*, step 3.
  2. If you find it: `complete --verdict fail --reason "<the fact>"`.
  3. If you do not: `ad ask --type user_only`, then `complete --verdict blocked --question <Q-id>`. Other ready work goes on.
- **`APPROVAL <id> <attempt> <step>`.** Leave the item running. Run `ad stop --condition needs_approval --detail "<step>"` and ask the user.
- **`SKILL_FAILED <id> <attempt> <skill>`.** Run `complete --verdict held --reason "<skill> did not load"`, then treat it as a fault.
- **No entry for an item, or a missing result path.** Run `complete --verdict fail` without `--result`. When there is no entry, take the attempt from the item's `briefs` in `ad status`.

Discard a reply whose `complete` says `not_running` or `stale_attempt`. It belongs to an older attempt.

When `complete` prints `"status": "failed"`, run `ad drop <id> --task <T> --cause <failed id>` for each id in its `dependants`, and name them with the failed item in the result.

## Chains

A chain entry's brief has one `ITEM` block per step. The executor does them in order, runs `ad checkpoint` after each writes step, and stops at the first step that fails or replies `BLOCKED`, `APPROVAL` or `SKILL_FAILED`. Handle its entries in step order, each as above.

- The step that stopped the chain takes its own verdict. Then complete each later step with `complete <id> --attempt <n> --verdict held --reason "chain stopped at <step id>"`. This uses no attempt and restores nothing.
- `changes` or `verify` on a step that did not finish prints `step_not_finished`. Record that step as a fail.
- If the executor's `ad checkpoint` failed with exit 3, it reports the error in that step's `RESULT`. Complete that step `held` with the error as reason, complete the later steps as above, then `ad stop --condition fault`.

After every pass, ask what the result changed. A discovery result or a result that contradicts the plan goes to decomposition.md, *Re-entry*. A new scope question goes to SKILL.md, *New scope question*.

## Workspace changes

An item added with `--writes` changes workspace files; git records the change, so no one writes or reads a diff. The workspace must be inside a git repository; otherwise `brief` faults with `not_a_git_repo` before changing anything. The brief's `Edits:` line tells the executor where to work:

- **In place**, when no other writes item is running or ready beside it (always in the main session): `brief` saves a checkpoint of the whole working tree, your uncommitted and untracked files included, under a hidden ref. Your index, branch and stash list are not touched. While it runs, `next` holds back every other writes item.
- **In a worktree**, when writes items are ready together: each gets `<T>/wt/<id>`, made from the checkpoint, and works and tests only there. Files your `.gitignore` excludes, such as installed dependencies, are not in the worktree.

Executors never copy the workspace. Do not edit the files a writes item may change while it runs. After the checklist passes:

1. Run `ad changes <id> --task <T>`. If a file is deleted (`D`) or `unlisted` is not empty (paths outside the plan the user saw), run `ad stop --condition needs_approval --detail "<id>: <the files>"` and ask first.
2. Run `complete --verdict pass`. It saves the change to `<T>/patches/<id>.patch`; for a worktree item it first applies the patch to the workspace and removes the worktree.
3. If it fails with `patch_conflict`, nothing has changed: run the `complete --verdict fail` its `next` line gives, so the retry is made against the current files.

A `fail`, `blocked` or `held` verdict restores the paths an in-place item changed, deleting the files it created, or removes the item's worktree. A chain's writes steps share one working tree, and each step's patch is its own part of the change. `finish` and `mark accepted` delete the task's refs and worktrees.

Submodule contents and files outside a sparse checkout are neither captured nor restored.

## Approvals

When the user replies to a `needs_approval` stop, run `ad resume --task <T>`, then do one of the following:

- **A change waiting for approval:** if approved, rerun *Workspace changes* steps 2 and 3, then handle any later chain steps' entries in order. If refused, run `complete --verdict fail --reason "<refusal>"`, which restores the files, then complete the later chain steps as *Chains* says.
- **An executor's `APPROVAL`:** run `complete --verdict held --reason "<the user's approval or refusal of the step>"`. The next brief carries it. Complete the later chain steps as *Chains* says.
- **A reversal:** see *Reversing*.

## Reversing

`answer` restores or removes the change of each affected item still running. Then reverse the patch of each affected item whose `was` is `done`, from the `patch` path in `affected`. Go latest first, using the order of each item's last `item_done` line in `<T>/record.jsonl`, so a later patch on the same lines comes off before the one it was applied on. Run git from the repository top (`git rev-parse --show-toplevel`):

1. Run `git apply -R --check <patch>`, then `git apply -R <patch>`.
2. If a patch does not reverse cleanly, run `ad stop --condition needs_approval` and ask.
3. If the user approves, run `git apply -R --reject <patch>`. It reverses the hunks that still apply and leaves each other hunk in a `.rej` file; name those files in the result.
4. If the user refuses, leave the files unchanged and name them in the result.

Run no `complete` for a reversal.
