# How atomic-decompose works, and why (0.4.0)

The design source and the test records are kept outside this repository: `v0.4-spec.md`, `v0.4-structure-review.md` and `v0.4-retest.md` in `project documentation/atomic-decompose-retro/` in the `testing` workspace. Their names carry a working version number; 0.2 was built in iterations numbered 0.2 to 0.4, which ship as one release. The shape described here is the one 0.2 introduced. 0.3.0 and 0.4.0 changed commands and fixed faults, and CHANGELOG.md lists them.

## Goal

Speed, cost and quality together. A small job should cost close to what a single agent spends on it. A big job should beat a single agent on quality, through a fresh context per part, a check on every item and one review, and on speed when its parts can run at once. More items or steps are fine when they make the job finish sooner or better. Only steps that buy neither are cut.

## Why 0.2 changed shape

The design before it (0.1.0 and the working iterations after it) split work by deliverable and ran writers to the same file side by side. Every worker re-read the same files and paid the same 4 KB reply protocol, and their diffs then had to be merged. Most of its bugs lived in the machinery that made that safe: merging the workers' diffs, acceptance reruns, approval stops, CHECK lines and shared-name warnings. The skill-authoring guidance points the same way: writes stay in one agent; extra agents add intelligence, not actions. So 0.2 lets the plan's file lists decide the shape, and the agent never judges what kind of job it has.

## The flow

1. **Plan:** the coordinator writes one JSON plan (format in SKILL.md). It holds the requirements, the questions with defaults, the task checks and the items. A writes item lists its `files` and `check_cmd`; a read-only item lists its `check`. `start` validates the whole plan and reports every problem at once. In a git repository it needs at least one commit (`no_commit`), and it prints, as `commits`, the branch the items will be committed on, for the coordinator to tell the user. `start` and `plan` refuse a planned file that git ignores (`ignored_files`): `done` reads changes from `git status`, which leaves ignored files out, so such an item could never commit.
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
   - It refuses edits to tracked files outside the item's `files`. Untracked files outside them, mostly build output, are named and left uncommitted. When the root is below the top of the repository, the same holds for the rest of the repository: a tracked file changed there since the run began is refused, with its name starting `../`.
   - It runs the item's checks and commits only the item's files, titled after the item, with an `AD-Item: <task>/<id>` trailer.
   - A failure prints the log tail, so it is fixed in the same session. The tail is at most 30 lines and 4,000 characters. After 3 failed tries the item fails and its dependants fail too. In a git repository its diff is saved as a patch, byte for byte, and its files are restored to the last commit. Without git nothing is restored, and the error says so.
   - A check that cannot run at all (`check_broken`) does not count as a try.
6. **`next`**, called after every executor has replied:
   - Unfinished items go back to pending, with a note and one more try counted.
   - Worktree commits that are not yet on HEAD are cherry-picked in plan order (`git cherry` skips those already there). A conflict does not stop the task: the pick is undone, the run's items go back to be redone on the current files, and the attempt stays on its branch, which the summary lists in `branches_left`. Tracked changes in a worktree that belong to no item are saved as `patches/<run>-outside.patch` and reported in `outside_changes`. That covers the whole worktree, not only the root: a tracked change outside the root goes into the patch, and a new file there is copied to the same place in the main folder.
   - The task checks run once per HEAD. A failure adds a fix item over the files that changed, at most 2 times; after that the task stops.
   - Then it starts the next round. If nothing is left to start, it stops for blocked items and their questions, or starts the review, or finishes.
7. **Review:** one read-only executor reviews the whole diff against the requirements. It runs when executors did any of the work; work the coordinator did itself, in view, is not reviewed (`--review always|never` overrides). `next` first tells the coordinator to say that the work has landed and passed its checks, so the user is not kept waiting on the review. `next` also names, in `unchanged` and in the review brief, any planned file an item never changed. Findings become fix items through `plan`, or named gaps. A `review.md` left from before a rework is renamed `review-before-<run>.md` when the next review starts, so an old review cannot pass for the new one.
8. **Finish:**
   - It refuses while tracked files changed during the task are uncommitted, measured against the snapshot taken at `start`, so the user's own work in progress is ignored.
   - It reruns the task checks only when HEAD moved since the last run.
   - It removes leftover worktrees and prints the summary the report needs. The summary's `next` names `references/report.md`, and its `review_state` is `missing` when a review was due and none was written.

## Stops

A stop is the only way the task waits on the user:
- `needs_user`: questions from `block`, or approvals.
- `land_blocked`: staged or uncommitted changes in the main folder keep git from landing a run. A run that clashes with work landed meanwhile does not stop: its items are redone on the current files, and the attempt stays on its branch.
- `task_checks_failed`.
- `user` or `fault`, from `stop`.

While stopped, `next` and `status` only print the stop, and `plan`, `decide` and `tune` are refused. Only `resume` clears a stop, with `--approve` or `--deny` for approvals. SKILL.md forbids the coordinator from approving a step itself.

## State

- **Files:**
  - `state.json` is the truth, replaced atomically.
  - `record.jsonl` is the append-only run record that `report.py` reads. A torn last line is cut on the next write.
  - `.lock` holds the owner's pid. Commands wait up to 60 s for it and take over a lock whose process is dead. One command at a time does the takeover, behind `.lock.takeover`. On Windows a lock is never taken over, because the liveness probe (`os.kill(pid, 0)`) ends the process there; a dead lock is deleted by hand. The Windows path is not tested. On other systems a dead lock still looks alive when another process has its pid or the file is damaged, so `task_locked` gives the same advice everywhere: when no command is running, ask the user, then delete the file.
- **Order of writes:** the state is written before the record line. A lost state write after a `done` commit is recovered on the rerun from the commit trailer.
- **Schema:** 0.2 uses schema 2, so it cannot resume tasks started by 0.1.0 or the unreleased build after it. Finish those first.

## What was removed, and why

Compared with 0.1.0 and the working iterations after it, the pyramid and its groups, deferred groups, `expand`, `small` and `chain_after` all go: runs and `plan` cover them. Also removed:
- `accept`, `complete` and the RESULT, CHECK and DEVIATION reply lines: the checks and the commits are the evidence.
- union merge and merge leaves: runs share no files.
- the add-time command lint, `shared_means`, head tracking, saved-attempt patches and the brief's auto-result marker.

## The user's files

- **`plan` and `start` refuse an item over a file with uncommitted changes** (`dirty_files`), tracked or new. An item restores its files to the last commit when it fails and commits them whole when it passes, so either way a change that is not the item's own would be lost or committed under the item's name. The half-made work of an item that is still open is the exception. There is no override flag: the user commits, stashes or undoes the change.
- **File names are passed to git as written**, and read back with `-z`. Each path is given as `:(literal)<path>`, so a file named `a*.txt` is that file, not a pattern, and a name git would print in quotes is matched as it is on disk. The environment variable `GIT_LITERAL_PATHSPECS` would do the same but is not used: the user's commit hooks inherit it, and a hook that lists `*.py` then finds nothing. A file name that is not UTF-8 is kept as its bytes all the way through the state and the output.
- **A handed-back task refuses every command that changes it** (`handed_back`). Worktrees and branches of runs that were still working are left where they are, because they may hold work the user wants. `log wrong_engagement` and `next` list them as `worktrees_left` and say how the user removes them.
- **A finished task stays finished.** `plan`, `resume` and `stop` are refused on it (`task_complete`); `mark --mark reworked` reopens it.
- **`plan` says when it did not apply an edit.** An item that is running or done is not edited; `plan` lists it in `ignored_edits` and its `next` names `annotate` and a new item.

## Decisions

- **The skill stays model-invoked** (decided for 0.4.0). The skill commits on the user's current branch, one commit per item, and it engages from the description, without the user naming it. The alternative was to make it run only when the user asks for it by name. That was rejected because the skill's use is the large, unclear task where the user does not know to ask for a method. What was done instead: `start` prints `commits`, one sentence that names the branch and says nothing is pushed, and its `next` begins with "tell the user what `commits` says". The question round, when there is one, comes before any commit. `log wrong_engagement` hands the task back. This was not measured with evals.
- **`check_cmd` runs through the shell** (`shell=True`), in the workspace, with the user's rights. It is the repository's own test command and often needs a pipe or `&&`. The plan file is written by the coordinator from the user's request, so a check command is as trusted as any command the agent runs. A task folder that came from somewhere else is not: `status` and `next` on it run the check commands and follow the paths it holds. Resume only a task folder that this workspace made.
- **A wrong check command goes through the user** (decided for 0.4.0). An executor that finds its `check_cmd` cannot run parks the item with a question, which stops the task. Two ways out were open: let `plan` run on a stopped task so the coordinator fixes the command at once, or keep the stop and have the coordinator tell the user, then `answer`, `resume`, `plan`, `next`. The first needs the coordinator, or the script on its behalf, to clear a stop the user never replied to, which SKILL.md forbids without exception. The second was taken: nothing in the script changes, and `references/recovery.md` now gives that order. The cost is one message to the user about a check that defines what "passes" means, which the user may want to know anyway.
- **Git is required for the safety the docs describe.** Without git there are no commits, no restore after a failure and no check for changes outside an item's files. Writers take turns.

## Size

0.2.0 had 13 commands, and its decompose.py was 1,596 lines. 0.3.0 adds `doctor` and `tune`, so it had 15 commands and 1,722 lines. `annotate`, in 0.4.0, makes it 16 commands and 1,750 lines. The script is then split with no change in behaviour: `decompose.py` keeps the parser and the entry point, and seven modules in `scripts/ad/` hold the rest (`common`, `state`, `plan`, `vcs`, `checks`, `runs`, `commands`). The last working iteration before the redesign had 23 commands and 3,762 lines. SKILL.md, recovery.md and report.md are the only docs left.
