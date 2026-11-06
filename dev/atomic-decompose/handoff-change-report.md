# Handoff change report: git-managed workspace changes (2026-11-05)

Executors no longer write or return diffs. A `--writes` item edits real files, either in place behind a git checkpoint or in its own worktree. The script records each change as a git-generated patch. Nothing is committed.

## Files changed and why

| File | Change |
| --- | --- |
| `skills/atomic-decompose/scripts/decompose.py` | New git section: `_git`, `git_top` (raises the `not_a_git_repo` fault), `snapshot` (temporary `GIT_INDEX_FILE`, `read-tree <base>`, `add -A`, `write-tree`), `checkpoint` (`commit-tree` with a fixed identity plus `update-ref refs/atomic-decompose/<task-id>/<id>-<attempt>`), `changed_files`, `write_patch` (`git diff --binary --full-index --no-renames`), `remove_worktree`, `end_writes` (restores by reverse-applying the attempt's own diff, or removes the worktree), `pass_writes`, and `clean_git`. Changes to commands: `add --writes`; `brief` chooses in place or a worktree and prints an `Edits:` line, and its reply rules forbid diffs and copies; `next` holds writes items while an in-place one runs; `complete` saves the patch on pass, applies a worktree patch after `git apply --check` (otherwise `patch_conflict`, exit 1), and restores on fail, blocked or held; `answer` restores running affected items and gives `affected[].patch`; new read-only `changes <id>`; `init` writes `<task>/.gitignore` containing `*`; `mark accepted` deletes refs and worktrees; `status` items gain `writes`, `worktree` and `patch`. During `resume` replay, git side effects are skipped (`Writer.replay`). New DM-2 leaf fields: `writes`, `checkpoint`, `worktree`, `patch`. The `item_started`, `item_done`, `item_retried`, `item_failed`, `item_blocked`, `item_held` and `marked` events gain data fields. |
| `skills/atomic-decompose/references/delegation.md` | *Diffs* is replaced by *Workspace changes*: in-place and worktree modes, the approval check through `ad changes` (any `D` or any path outside the plan means `needs_approval`) before `pass`, `patch_conflict` leading to `fail`, the assumption that the user does not edit the same files while an item runs, and ignored files being absent from worktrees. *Replies* steps 4 and 5, *Approvals* and *Reversing* (patch path from `affected`, run git from the repository top) are updated. |
| `skills/atomic-decompose/references/decomposition.md` | Documents `--writes`. The sentence saying a writes item returns a diff is removed. |
| `skills/atomic-decompose/SKILL.md` | Must change: *Changed answer* pointed to *Diffs* step 1, and its "reverse their diffs" now says "patches". The Faults row now names `git_missing`, `not_a_git_repo` and `git_failed`. |
| `README.md` | Requirements now say a git repository is needed for writes items. The "add that to your `.gitignore`" advice is removed, because the task folder ignores itself. The install note says the skill edits files through git checkpoints and worktrees. |
| `dev/atomic-decompose/selftest.py` | `test_coordinator_diffs` is replaced by `make_repo` and the other helpers plus four tests (below). |
| `dev/atomic-decompose/CHANGELOG.md` | New *Unreleased* entry. |
| `dev/atomic-decompose/progress.md` | Dated 2026-11-05 entry: what changed, why, the mutation checks, the load size and the TDD revision items. |

## Behaviours and their assertions (`selftest.py`)

| Behaviour | Test, and the assertion message it checks |
| --- | --- |
| Checkpoint captures uncommitted (staged and unstaged) and untracked files, and leaves the index, status and stash list unchanged | `test_in_place_checkpoint`: "checkpoint holds unstaged, untracked and staged changes"; "checkpoint leaves the user's index, status and stash list alone" |
| `changes` lists M/D/A files, including a tracked file under an ignore rule | `test_in_place_checkpoint`: "changes lists the item's files…" |
| Fail restores only the changed paths and deletes created files (and their new folders) without touching the index | `test_in_place_checkpoint`: "fail restores changed and deleted paths and deletes created files"; "restore leaves the index alone" |
| Pass saves a binary-safe patch, leaves the edits in place, and `item_done` records the patch | `test_in_place_checkpoint`: "pass saves a binary-safe git patch"; "pass leaves the edits in place…"; "item_done records the patch" |
| `next` holds a second writes item while an in-place one runs, and releases it afterwards | `test_writes_hold_and_worktrees`: "next holds a writes item while an in-place writer runs" (and `brief` is refused with `not_ready`); "the held writes item is ready once…" |
| Two ready writes items each get a worktree, named in the brief and built from the checkpoint | `test_writes_hold_and_worktrees`: "writes items ready together each get a worktree named in the brief"; "the worktree starts from the checkpoint…" |
| A worktree pass applies its patch, saves it and removes the worktree | "a worktree pass applies its patch to the workspace and saves it"; "a worktree pass removes the worktree" |
| A clashing worktree patch changes nothing, exits `patch_conflict`, and the follow-up fail removes the worktree and retries in place | "a clashing worktree patch changes nothing and names the fail command"; "the clashing item is retried and its worktree removed"; "the retry runs in place against the current files" |
| Reversal uses the saved patches: earliest first fails, latest first restores | `test_reverse_patches`: "affected names each done item's patch"; "reversing earliest first fails"; "reversing the saved patches latest first restores the files" |
| The task folder (state, patches, worktrees) adds nothing to `git status --porcelain` | "the task folder adds nothing to git status"; "worktrees inside the task folder add nothing to git status"; "task folder with patches still adds nothing to git status" |
| `mark accepted` removes refs and worktrees (a stale one included) and keeps state, record, results and patches | "mark accepted removes the task's refs and worktrees"; "mark accepted keeps state, record, results and patches" |
| A writes item outside a git repository, or without git, faults (exit 3) before any change; an item without `--writes` needs no git | `test_writes_needs_git`: "a writes item outside a git repository faults before any change"; "git missing faults before any change"; "an item without --writes needs no git" |

## Selftest output

```
$ python3 dev/atomic-decompose/selftest.py
selftest: all assertions hold
(exit 0)
```

Mutation checks: I broke each behaviour, confirmed the selftest fails, then restored the file and confirmed it matches (`cmp`). All nine runs failed with exit 1:

- `next` hold off
- reverse-apply restore off
- `.gitignore` not written
- ref deletion off
- in-place look-ahead off
- `read-tree` off (caught only after I added the tracked-but-ignored `keep.log` case; before that, the mutant passed)
- worktree `git apply` off
- clash check off
- `patch` field not stored

I also checked by hand a workspace root that is a subfolder of the repository. The brief names `wt/<id>/sub`, and the patch paths are relative to the repository top.

## Load-token figure

The files loaded before the first work item are SKILL.md (8,212 chars), decomposition.md (4,507) and delegation.md (6,917). Delegation.md is read at step 4, before the first brief. That totals 19,636 chars, about **4,910 tokens** (chars/4). The NFR-8 budget is 5,000; the old figure was about 4,650. SKILL.md plus decomposition.md alone is about 3,180.

## Not done, and why

- **The TDD is not edited**, because the spec is read-only. The revision items are listed in progress.md: DD-4, DD-8, a new checkpoint/worktree decision, API-3, API-5, API-7, API-8, DM-2, DM-5, the §5 flows, §8, DD-16 and §9.
- **`patch_conflict` does not fail the item automatically.** `complete --verdict pass` exits 1 with nothing changed, and its `next:` line is the exact `complete --verdict fail` command. This keeps `resume` replay deterministic: a replayed `pass` cannot become a fail. It matches today's rule that the coordinator records the clash.
- **Crash window not handled.** If the process dies after a worktree patch is applied but before its `item_done` line is written, rerunning `complete` reports `patch_conflict`, because the patch is already applied. That window is small, and it is not handled.
- **A running executor can keep editing after a restore.** `answer` restores the files of a running affected item, but the script cannot stop that executor, which may keep writing to the files until it replies. Its reply is then discarded.
- **Ignored files are missing from worktrees.** Files the repository ignores, such as `node_modules` or a `.venv`, are not in a worktree, so tests there may need a setup step. delegation.md says so.
- **Snapshots rehash every file.** Each snapshot starts from a fresh temporary index, so it is slow on very large trees. It is marked with a `ponytail:` comment.
- **Not in my scope:** `dev/atomic-decompose/HOW-IT-WORKS.md` is untracked and was not written by me. It still describes the diff flow in places, so I left it alone.
- **Evals not checked against the change:** the evals (`evals.json`) contain no diff expectations, so they are unchanged. They have not been rerun.
- **No linter available:** neither ruff nor pyflakes is installed, so only the selftest and `--help` were run.
