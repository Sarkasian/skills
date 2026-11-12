# How atomic-decompose works, and why (0.2)

The design source and the test records are kept outside this repository: `v0.4-spec.md`, `v0.4-structure-review.md` and `v0.4-retest.md` in `project documentation/atomic-decompose-retro/` in the `testing` workspace. Their names carry a working version number; 0.2 was built in iterations numbered 0.2 to 0.4, which ship as one release.

## Goal

Speed, cost and quality together. A small job should cost close to what a single agent spends on it. A big job should beat a single agent on quality, through a fresh context per part, a check on every item and one review, and on speed when its parts can run at once. More items or steps are fine when they make the job finish sooner or better. Only steps that buy neither are cut.

## Why 0.2 changed shape

The design before it (0.1.0 and the working iterations after it) split work by deliverable and ran writers to the same file side by side. Every worker re-read the same files and paid the same 4 KB reply protocol, and their diffs then had to be merged. Most of its bugs lived in the machinery that made that safe: merging the workers' diffs, acceptance reruns, approval stops, CHECK lines and shared-name warnings. The skill-authoring guidance points the same way: writes stay in one agent; extra agents add intelligence, not actions. So 0.2 lets the plan's file lists decide the shape, and the agent never judges what kind of job it has.

## The flow

1. **Plan:** the coordinator writes one JSON plan (format in SKILL.md). It holds the requirements, the questions with defaults, the task checks and the items. A writes item lists its `files` and `check_cmd`; a read-only item lists its `check`. `start` validates the whole plan and reports every problem at once.
2. **Ask:** `next` prints the questions from the plan once, and the coordinator asks them in one round.
3. **Runs:** each `next` groups the ready items by shared file into runs.
   - An item waiting only on items in one run joins that run, so a chain stays with one executor.
   - An item waiting on two or more runs waits for a later round.
   - Read-only items each form their own run.
   - The two smallest runs are packed together until there are at most `max_parallel`.
4. **Where a run works:**
   - One run, not in delegate mode: the coordinator does it itself (`do_yourself`). No hand-off, worktree or merge.
   - Two or more writes runs: each gets a git worktree on its own branch.
   - Without git, writers take turns.
5. **`done`** is called by whoever does the item.
   - It refuses edits to tracked files outside the item's `files`. Untracked files outside them, mostly build output, are named and left uncommitted.
   - It runs the item's checks and commits only the item's files, titled after the item, with an `AD-Item: <task>/<id>` trailer.
   - A failure prints the log tail, so it is fixed in the same session. After 3 failed tries the item fails: its diff is saved, its files are restored, and its dependants fail too.
   - A check that cannot run at all (`check_broken`) does not count as a try.
6. **`next`**, called after every executor has replied:
   - Unfinished items go back to pending, with a note and one more try counted.
   - Worktree commits that are not yet on HEAD are cherry-picked in plan order (`git cherry` skips those already there). A conflict stops the task.
   - The task checks run once per HEAD. A failure adds a fix item over the files that changed, at most 2 times; after that the task stops.
   - Then it starts the next round. If nothing is left to start, it stops for blocked items and their questions, or starts the review, or finishes.
7. **Review:** one read-only executor reviews the whole diff against the requirements. It runs when executors did any of the work; work the coordinator did itself, in view, is not reviewed (`--review always|never` overrides). `next` first tells the coordinator to say that the work has landed and passed its checks, so the user is not kept waiting on the review. `next` also names, in `unchanged` and in the review brief, any planned file an item never changed. Findings become fix items through `plan`, or named gaps.
8. **Finish:**
   - It refuses while tracked files changed during the task are uncommitted, measured against the snapshot taken at `start`, so the user's own work in progress is ignored.
   - It reruns the task checks only when HEAD moved since the last run.
   - It removes leftover worktrees and prints the summary the report needs.

## Stops

A stop is the only way the task waits on the user:
- `needs_user`: questions from `block`, or approvals.
- `land_blocked`: staged or uncommitted changes in the main folder keep git from landing a run. A run that clashes with work landed meanwhile does not stop: its items are redone on the current files, and the attempt stays on its branch.
- `task_checks_failed`.
- `user` or `fault`, from `stop`.

While stopped, `next` and `status` only print the stop, and `plan` and `decide` are refused. Only `resume` clears a stop, with `--approve` or `--deny` for approvals. SKILL.md forbids the coordinator from approving a step itself.

## State

- **Files:**
  - `state.json` is the truth, replaced atomically.
  - `record.jsonl` is the append-only run record that `report.py` reads. A torn last line is cut on the next write.
  - `.lock` holds the owner's pid. Commands wait up to 60 s for it and take over a lock whose process is dead.
- **Order of writes:** the state is written before the record line. A lost state write after a `done` commit is recovered on the rerun from the commit trailer.
- **Schema:** 0.2 uses schema 2, so it cannot resume tasks started by 0.1.0 or the unreleased build after it. Finish those first.

## What was removed, and why

Compared with 0.1.0 and the working iterations after it, the pyramid and its groups, deferred groups, `expand`, `small` and `chain_after` all go: runs and `plan` cover them. Also removed:
- `accept`, `complete` and the RESULT, CHECK and DEVIATION reply lines: the checks and the commits are the evidence.
- union merge and merge leaves: runs share no files.
- the add-time command lint, `shared_means`, head tracking, saved-attempt patches and the brief's auto-result marker.

There are 13 commands and decompose.py is 1,596 lines. The last working iteration before the redesign had 23 commands and 3,762 lines. SKILL.md and recovery.md are the only docs left.
