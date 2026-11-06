# Changelog

SemVer. Major: rename, trigger-scope change, removed script/flag, config schema break. Minor: new optional config/reference, deprecation. Patch: wording fixes that pass evals.

## Unreleased
- Workspace changes go through git instead of hand-written diffs. New `add --writes` flag marks an item that changes workspace files. `brief` saves a checkpoint of the whole working tree (uncommitted and untracked files included) under `refs/atomic-decompose/<task-id>/<item>-<attempt>` without touching the user's index, branch or stash list. A lone writer edits in place; writers ready together each get a worktree under `<task>/wt/<id>`, and `next` holds other writers while an in-place one runs. `complete --verdict pass` saves `<task>/patches/<id>.patch` (a worktree's patch is applied first; a clash exits 1 `patch_conflict` with nothing changed); `fail`, `blocked`, `held` and a changed answer restore the changed paths or remove the worktree. New read-only `changes <id>` lists the item's files for the approval check. `answer` lists each affected done item's `patch`; `status` items gain `writes`, `worktree`, `patch`. `init` writes `<task>/.gitignore` (`*`). `mark accepted` deletes the task's refs and worktrees. New faults: `not_a_git_repo`, `git_missing`, `git_failed`. Executors no longer write diffs into result files.
- Build of the signed-off TDD (2026-11-06):
  - Script-run checks: `add --check-cmd`; `verify <id>` runs them in the item's working tree with a per-command `check_timeout_s` (default 600; the process group is killed); `complete --verdict pass` refuses with `checks_not_passed` until `verify` passes; `no_check_commands`.
  - `finish` reruns the command entries of done writes items in the workspace. A failure exits 1 `checks_failed` and names one fix leaf; commands a failed fix leaf holds are skipped and listed as `unresolved`. `finish` now removes the task's refs and worktrees.
  - Chains: `add --chain-after` (`chain_invalid`, `max_chain` default 5). `next` returns a chain as one entry, and its writes steps share one tree. New executor command `checkpoint <step-id>` writes the step's `-end` ref; each step's `changes`, patch and `verify` cover its own span; `step_not_finished`.
  - Other script changes:
    - `log plan_shown` and `changes` `unlisted`;
    - `drop --unneeded` (`patch_not_reversed`);
    - `next` `one_entry` and an explicit `init --mode delegate` (`mode_explicit`);
    - scope questions block the leaves that need them;
    - `asked` numbers the opening round 1;
    - `brief` refuses a writes item during a merge, rebase, cherry-pick, revert, am or bisect, or in a bare repository;
    - `answer_changed` records `affected`;
    - `add` refuses `--small --writes`;
    - the brief numbers judgement entries, lists command entries, adds the `Outside this item:` line and asks for `CHECK` pointers.
  - Source folder only (not installed): `report.py` (C-8) `release` and `weekly`, Cursor only for now. Token totals are null until the Cursor usage-export columns are confirmed.
  - Coordinator: start-early question round where the host has a blocking question tool, plan notice, executors held on a new-session entry, chain reply handling, and the `finish` fix leaf.

## 0.1.0
- Initial version: coordinator instructions, `decompose.py` state script, decomposition and delegation references. Installed with `npx skills` or `gh skill`; the planned `install.py` (TDD C-6) is replaced by those installers.
