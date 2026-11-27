# Changelog

SemVer. Major: rename, trigger-scope change, removed script/flag, config schema break. Minor: new optional config/reference, deprecation. Patch: wording fixes that pass evals.

## 0.4.0 (2026-11-27)

Not tagged. A new command, `annotate`, and the fixes from an audit of the skill. Two of the fixes stop the script deleting or overwriting the user's files.

Not tested: the task evals and the trigger evals were not rerun for this release, because they need a headless agent CLI. Nothing here was run on Windows. The selftest ran on Linux with Python 3.12.

### Added

- Added `annotate --item <id> --note "<direction>" [--source user|system]`: it adds a note to an item, and the item's next brief carries it as `Note [from <source>]: ...`. The note is kept as one line of at most 5,000 characters. A `done` or `dropped` item is refused, and a running item gets a warning that only a retry reads the note. `annotate --item <id> --list` prints the item's notes. A new command is a minor change, so the next release is 0.4.0.
- `start` prints `commits` in a git repository: one sentence that names the branch (or the detached HEAD) the items are committed on and says nothing is pushed. Its `next` begins with "tell the user what `commits` says". The skill engages without being named, so the user hears where the commits go before the first one.
- The summary that `finish` and the last `next` print has four new fields. `action` is `report`. `review_state` is `missing` when a review was due and no review was written; before, that case looked the same as "no review needed". `branches_left` lists the branches that hold an attempt that clashed on landing. `outside_patches` lists the patches described under "Fixed" below. The summary's `next` names the full path of `references/report.md` and the `mark` command.
- `decide` prints a `next`, like every other command.
- Every flag and argument has help text.

### Fixed: the user's files

- **A failed or blocked item no longer deletes tracked files when `--root` is below the top of the git repository.** The restore compared file names in two different forms, took every tracked file of the item for a new file, and removed it from the index and the disk. The same happened to a file whose name git prints in quotes (a `"`, a tab, a non-ASCII letter). The names are now read with `-z` and compared as they are.
- **`plan` refuses an item over a file with uncommitted changes** (`dirty_files`), tracked or new, as `start` always did. Before, such an item committed the user's change under its own name when it passed, and reverted or deleted the file when it failed. The half-made work of an item that is still open does not count. There is no flag to override it.
- **`finish` no longer tells the coordinator to add an item over uncommitted changes** (`uncommitted_changes`). `plan` now refuses that. The advice is to ask the user to commit, stash or undo them, and the error is `needs_user`.
- **A saved patch is written byte for byte.** Before, a file with CRLF line ends gave a patch that did not apply, and a file that is not UTF-8 crashed `done` with a traceback after the third failed try.
- **File names are passed to git as written** (`GIT_LITERAL_PATHSPECS=1`). Before, restoring an item's file named `a*.txt` could also revert the user's `ab.txt`, and the saved patch held both.
- **`outside_files` tells the executor to undo only the changes it made**, and to report a changed file that is not its own. Before, it said "undo those changes", which could revert the user's edit.
- **A worktree's tracked changes that belong to no item are saved** as `patches/<run>-outside.patch` and reported as `outside_changes`. Before, they went with the worktree without a word.

### Fixed: other

- **Windows: the script no longer asks whether a lock's process is alive.** It did that with `os.kill(pid, 0)`, which on Windows ends the process. On Windows a lock is now never taken over, and `task_locked` says to delete the lock file when no command is running. Not tested on Windows.
- **`start` refuses a git repository with no commit** (`no_commit`). Before, it failed with a raw git error.
- **Item ids in a plan file that look like generated ids (`0`, `1`, `2`) no longer merge items.** Before, the item with id `1` overwrote the item that had just been given the generated id 1, and `depends` pointed at the wrong item.
- **Without git, a failed item's error no longer says "its files are back as they were".** Nothing is restored without git. The error says the files are left as they are.
- **An error message quotes at most 30 lines and 4,000 characters of a log**, and reads only the end of the file. A check that printed one very long line used to put all of it in the error. Lists of file names in errors stop at 20, with a count of the rest.
- **Two commands that find a dead lock at the same moment can no longer both take it.** The takeover is done by one command at a time, behind `.lock.takeover`. The race was found by reading the code and was not reproduced.
- **Input that was accepted without a word is refused:** a `check_timeout_s` that is not a whole number of seconds, 1 or more (`plan_invalid`); `log --data` that is not a JSON object (`bad_input`); `"status": "dropped"` on an item that is done, running or unknown (`plan_invalid`).
- **A handed-back task refuses every command except `status`, `next`, `resume` and `log`** (`handed_back`). Before, `plan`, `done` and others still ran on it.
- **The script finds its `ad/` package under `python3 -P`, `-I` and `PYTHONSAFEPATH`,** and writes no `__pycache__` into the skill folder.
- `done` records a read-only item's result path when `--result` is left out. A usage error's `next:` line is the whole `--help` command. `status` on a complete task names `finish`.

### Changed

- **The question round's item list is `plan_items`.** It was `plan`, the key `start` also uses for the path of `plan.json`, so on `start` the path replaced the list.
- SKILL.md frontmatter: `license: MIT` added, `metadata.owner` removed. No change in behaviour.
- SKILL.md section 3 moves to `references/report.md`, read when the action is `report`. The text is unchanged. SKILL.md goes from 5,998 to 5,574 characters, against its cap of 6,000. `report.md` now also covers `review_state`, `branches_left`, `outside_patches`, the branch the commits are on, and the `unmarked` mark.
- `decompose.py` is split into modules, with no change in behaviour. `scripts/decompose.py` keeps the parser and the entry point, and the command to run is the same. `scripts/ad/` holds `common`, `state`, `plan`, `vcs`, `checks`, `runs` and `commands`, one per section of the old file. `shelve` moves from the commands to `runs`, where its caller is, and `LOCK_WAIT_S` moves to `state`, its only user. The selftest no longer caps the script's line count (it was 1,750). The agent runs the script and never loads it, so its length costs nothing per run, and the cap had led to argument help and blank lines being cut to fit. The 6,000-character cap on SKILL.md stays.
- `references/recovery.md` has a section for every error code the script prints. New: `no_result`, `not_running`, `out_of_order`, `plan_invalid`, `plan_unreadable`, `files_not_found`, `nested_repo`, `no_commit`, `dirty_files`, `task_complete`, `bad_input`, `checks_failed`, `not_complete`, `handed_back`. It says what a failed item leaves behind with and without git, and what to do about a dead lock on Windows.
- Every line that deletes a file has its own `lint: no-dry-run: <reason>` comment directly above it, in `ad/state.py`, `ad/vcs.py` and `ad/commands.py`. Each removes one of: the task's own lock, takeover marker or temporary state file; the task folder `start` just created; a failed attempt's new file, after a patch of it is saved.
- SKILL.md is unchanged apart from its version. It is 5,574 characters, against its cap of 6,000.
- HOW-IT-WORKS.md: the title names this version; "a conflict stops the task" is corrected (the items are redone); new sections "The user's files" and "Decisions". The decisions recorded are that the skill stays model-invoked, that `check_cmd` runs through the shell, and what is lost without git.

### Tests and evals

- The selftest has 18 new tests, one or more for each fix above. Each was run against the 0.3.0 script and fails there. One test runs the real command line as a subprocess from another folder, with `python3 -P` (Python 3.11 or later) and `python3 -I`. The selftest removes its temporary folder when it passes and keeps it, and prints its path, when it fails.
- `trigger_evals.json`: 9 new negative queries that are near misses (a review of existing work, a one-file bug fix, an explanation "step by step", a question that uses the words "break down" and "plan"). It has 61 queries, 21 positive and 40 negative.
- `evals.json`: three new cases with fixtures under `evals/files/`. Case 9 has a check that cannot pass (`failing-check/`), case 10 has three writers with separate files (`parallel-writers/`), and case 11 has an uncommitted user change in a planned file (`dirty-tree/`). Each has a `setup` list of shell commands to run in the workspace before the prompt (a `git init` and first commit, and for case 11 the uncommitted change). The eval harness is outside this repository and does not read `setup` yet. In the old cases, "batches" is now "runs", and case 7 expects the skill's name where it said the path of its SKILL.md.
- None of the eval cases, old or new, was run for this release.
- SKILL.md, read-only items: research items that share one local research engine are chained with `depends`, and a long research pass is allowed in the item's `goal` with a time limit. `deep-research-run` 0.2.0 relies on both.

## 0.3.0 (2026-11-16)

Not tagged. The number of runs that work at once is now a setting, where 0.2.0 had the fixed number 4.

### Added

- **`max_parallel` is set per task**, by the first of these that is set when `start` runs:
  1. `start --max-parallel N`;
  2. `max_parallel` in the plan file;
  3. the `AD_MAX_PARALLEL` environment variable (empty counts as not set);
  4. the user config file: `$XDG_CONFIG_HOME/atomic-decompose/config.json`, or `~/.config/atomic-decompose/config.json` when that variable is not set; on Windows, `%APPDATA%\atomic-decompose\config.json`;
  5. the project config file: `.atomic-decompose.json` in the top folder of the git repository, or in `--root` when there is no repository;
  6. the default, 4.

  A config file is a JSON object such as `{"max_parallel": 2}`. `start` prints the value as `max_parallel` and where it came from as `max_parallel_layer`. The finish summary prints `max_parallel`.
- **`doctor --root <folder>`** prints the value a `start` in that folder would get, the layer it comes from, both config file paths, whether the folder is in a git repository (parallel writers need worktrees), the CPU count, and every setting that cannot be used. It needs no task and changes nothing.
- **`tune --max-parallel N --task <T>`** changes the value of a task that has started. The new value applies from the next round, and the runs already working are left as they are.

### Changed

- **`max_parallel` must be an integer from 1 to 64.** On 0.2.0, `start --max-parallel 0` crashed with an `IndexError`.
- **`start` refuses when the first setting that is set cannot be used.** It does not fall through to a lower one. A setting cannot be used when its value is not an integer from 1 to 64, or when its config file is not JSON, is not a JSON object, or cannot be read. The error names the layer and, for a file, its path. Its code is `plan_invalid` for the plan's field and `bad_input` for the others. The environment variable and the two files are the user's to fix (`resolves: needs_user`). An unusable setting below the one that applies does not stop `start`: it is listed in `config_problems`. `doctor` reports a refusal as `max_parallel: null` with the layer, and still exits 0.
- **`plan` refuses a plan file whose `max_parallel` is not the task's value** (code `plan_invalid`), and its `next:` line names `tune`. Before, `plan` ignored the field without a word. The settings are read once, at `start`, and `tune` is the one command that changes the value afterwards.
- **The task's `plan.json` no longer carries each item's status.** The file was written once and went stale, and `plan` reads `"status": "pending"` as "retry this item". So a later `plan`, even one that only added an item, put failed items back to pending with their tries reset, and cleared blocked ones. In a plan file, `status` is now only an instruction (`"dropped"`, or `"pending"` to retry), and the `status` command shows the statuses. A `plan.json` written by an earlier build keeps its old statuses until `plan` rewrites it. `plan` also compares each open item with the file as a plan file is read, and leaves out the need that `block --question` gives an item. Before, that need (which the file does not have) and a goal that ends in a line break (which reading a plan file strips) each counted as an edit, so a `plan` that changed nothing about an item unblocked it without the user being asked, or reset a failed fix item. A real edit to an item blocked on a question still withdraws the question, which is how the `check_broken` recovery reruns the item.
- **SKILL.md is 5,815 characters (it was 7,998); the selftest cap is 6,000 (it was 8,000).** The *Ask* and *Faults* sections and the four action bullets of *Run* are gone: each said what the script prints in the `next` of the action or error it belongs to. Three telemetry instructions are gone too: `log compaction` and `log tokens`, which nothing reads, and `log asked_again`, so weekly metric M-1 no longer counts a re-ask the coordinator reports about itself. New: `--max-parallel <N>` beside `--mode`, and a pointer to `--help`. The `--mode delegate` sentence now says "delegate the work" and "executors" where it said "sub-agents", so the file has one word for whoever does a run. The name and description are unchanged. The task and trigger evals were not rerun.
- decompose.py is 1,722 lines; the selftest cap is 1,750 (it was 1,600).

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
