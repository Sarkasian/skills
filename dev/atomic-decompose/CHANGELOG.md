# Changelog

SemVer. Major: rename, trigger-scope change, removed script/flag, config schema break. Minor: new optional config/reference, deprecation. Patch: wording fixes that pass evals.

## 0.2.0 (2026-11-12)

Not tagged. A redesign of the unreleased build that followed 0.1.0 (git checkpoints, script-run checks, chains). Test runs showed that build made a small model slower and worse than the same model working alone, so the flow was cut down to what a run needs. It was built in several working iterations, numbered 0.2 to 0.4 while in progress. They ship as this one release, and their separate notes are not kept. It is a major change by the rules above, kept at 0.x.

### Changed

- **Runs replace per-item briefs and chains.** The plan's `files` lists group items into runs:
  - shared files mean one executor, in order;
  - separate files run at once, each in a worktree, at most 4 at a time;
  - a single run is done by the coordinator itself.
- **`done` replaces `complete`, `verify`, `changes` and `checkpoint`.** Whoever does an item calls it when the item is finished. It refuses tracked edits outside the item's files, runs the checks, prints the log tail on a failure (3 tries in the same session), and commits the item. It also refuses an item while an earlier item of the same brief is still running (`out_of_order`).
- **`next` drives everything.** It lands worktree commits in plan order, runs the task checks once per HEAD (a failure adds a fix item, at most 2), starts the next round, stops for the user, starts the review, or finishes.
- **The plan is one JSON file.** `start --plan` lists every problem at once, and accepts items as a list or an object and strings for lists. `plan` re-applies the task's own `plan.json` with ids, replacing `add`, `drop` and `validate`.
- **`start` refuses input it cannot work with:**
  - a root that holds none of the planned files (`files_not_found`; `--new-files` allows a plan of new files only);
  - a planned file in a git repository nested below the root (`nested_repo`);
  - planned files with uncommitted changes;
  - a `check_cmd` split into words (`plan_invalid`).
- **The brief** is about 1–2 KB: the folder, the request, settled answers, decisions, and each item's files, goal, checks and exact `done` command. One executor does all of a brief's items, one at a time. There are no reply lines.
- **The review** runs once, read-only, when executors did any of the work. Work the coordinator did itself is not reviewed. The user is told the work has landed before the review starts.
- **Unchanged planned files.** `done` records the planned files an item did not change. `next` names them in `unchanged` when the run closes, and the review brief lists them.
- **Commits:** always one per item in a git workspace, on the current branch, titled after the item, with an `AD-Item: <task>/<id>` trailer. Before, changes sat behind checkpoints until the result was accepted.
- **Stops:** only `resume` clears a stop; `--approve` and `--deny` carry the user's reply.
- **State:** schema 2, written before the record line; `done` recovers a lost write from the trailer. A lock whose process is dead is taken over. A task started by 0.1.0 or the build after it cannot be resumed, and there is no converter: finish open tasks before upgrading.
- **Docs:** SKILL.md is 7,998 characters with a full plan example. references/decomposition.md and delegation.md are removed, and recovery.md is new.

### Removed

These commands are gone: `init`, `add`, `drop`, `validate`, `ask`, `asked`, `brief`, `complete`, `verify`, `changes`, `checkpoint` and `handoff`. Also gone: groups, deferred groups, `small`, `chain_after`, checkpoint refs under `refs/atomic-decompose/`, the CHECK and RESULT reply lines and the profile config files. 13 commands are left.

### Known limits (`ponytail:` in the code)

- New untracked files outside an item's files are left uncommitted and named, not refused.
- The run packer merges the two smallest runs, with no estimate of their size.
- An item's check can pass without the item's own tests. `next` names the planned files an item never changed (`unchanged`), but does not refuse the item: a plan may list a file an item turns out not to need.
- `--new-files` switches off the check that the planned files exist, and a coordinator can pass it without need.
- A `check_cmd` split into words is caught only when one word is a flag; `["npm", "test"]` passes.
- Worktrees link the repository's ignored top-level entries (`.venv`, `.env`), so parallel checks that write into one shared ignored folder can race.
- decompose.py is 1,596 lines, over the design's 1,500 target; the selftest cap is 1,600.

## 0.1.0
- Initial version: coordinator instructions, `decompose.py` state script, decomposition and delegation references. Installed with `npx skills` or `gh skill`; the planned `install.py` (TDD C-6) is replaced by those installers.
