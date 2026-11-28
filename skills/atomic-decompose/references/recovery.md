# Recovery

Read the section for the error code you got. Each section says who acts and what to run. One rule holds in all of them: never undo, revert or delete a change you did not make. Ask the user.

## check_failed, item_failed

These go to the executor. Read the log tail in the message and fix the work, then run `done` again. A long log is cut to its last lines and characters, and the message names the whole log file. After 3 failed tries the item fails, and work that depends on it fails too. Go on to your next item.

- **In a git repository** the item's files go back to the last commit, and its last diff is saved under `<T>/patches/` (`git apply` gives it back). The message then says `its files are back as they were`.
- **Without git**, or when the diff could not be saved, nothing is restored. The message says `its files are left as they are`, and the failed attempt is still in them.

The coordinator names failed items in the report, or retries one by editing it in `plan.json` and giving it `"status": "pending"`, then running `plan` and `next`.

## check_broken

The check command itself could not run: the command was not found, or the module is missing. It does not use up a try. If the command is wrong, the executor parks the item with `block <id> --question "the check <cmd> is wrong: <why>"`. That question stops the task (`needs_user`) like any other, and `plan` is refused while it is stopped. So the coordinator tells the user that the check is wrong and what it will run instead, records the reply with `answer`, and runs `resume`. Only then does it fix `check_cmd` in `plan.json` and run `plan`, then `next`: the item reruns with the new check. The `next` of `resume` says the same: after an answer to an item's question it names `plan` before `next`, because `next` starts the item again as it is and `plan` does not edit a running item.

## outside_files, no_changes, no_result, not_running, out_of_order

These go to the executor.

- **outside_files:** `done` commits only the item's `files`. Undo the edits you made to the other files. A name that starts with `../` is a file of the repository outside the task's root, which no item can change. If they belong to a later item in the same run, keep them aside until that item's turn. If the goal really needs another file, ask with `block <id> --approval "change <file>: <why>"`. If you did not change one of the files named, do not revert it: reply `files changed that I did not change` and stop.
- **no_changes:** do the goal. If the item truly needs no change, run `done <id> --no-change "<why>"`.
- **no_result:** a read-only item has no result file. Write the result to the path the message names, then run `done` again.
- **not_running:** the item is finished, failed or blocked, so it is not yours to finish. Go on to the item the `next:` line names.
- **out_of_order:** a brief's items are done in order by one executor. Do the item the message names first.

## Refused by start or plan

- **plan_invalid:** the message lists every problem in the plan file. Fix them all and rerun the same command. `"status": "dropped"` works only on an item that is pending, failed or blocked; `check_timeout_s` is a whole number of seconds, 1 or more.
- **plan_unreadable:** the plan file is not there or cannot be read. Give the right path.
- **files_not_found:** none of the planned files is under `--root`. Give `--root` the folder the request changes. If every file really is new, add `--new-files`.
- **nested_repo:** a planned file is in a git repository below the root. Rerun `start` with the `--root` the message names.
- **no_commit:** the git repository has no commit, so there is nothing to restore a failed item to. Ask the user to make a first commit, then rerun `start`.
- **ignored_files:** git ignores a planned file (`.gitignore`), so `done` could never see the item's change or commit it. Take the file out of the item's `files`: build output is made by a check, not committed by an item. If the file really is the item's work, ask the user to stop ignoring it. Then rerun the command.
- **dirty_files:** a file the plan gives to an item has uncommitted changes, or is a new file git does not track. An item would commit those changes as its own, or lose them when it fails. Ask the user to commit, stash or undo them, then rerun the command. `plan` does not refuse the half-made work of an item that is still open.
- **task_complete:** the task is finished, so `plan`, `resume` and `stop` are refused. Only the user's rework reopens it: `mark --mark reworked --reason "<reason>"`.
- **bad_input:** a flag or value is wrong. The `next:` line is the `--help` command to run.

## Stops: needs_user, land_blocked, task_checks_failed

- **needs_user:** questions from executors, or approvals. Ask the user all of them in one message, record the answers, then `resume` (with `--approve` or `--deny` for approvals).
- **land_blocked:** git will not put a finished run's commits on HEAD, because of staged or uncommitted changes in the main folder. Tell the user what git named. Once they commit, unstage or stash it, run `resume`, then `next`.
- A run whose commits clash with work that landed meanwhile does not stop: its items go back to be redone on the current files. The earlier attempt stays on the branch the note names, and the summary lists that branch in `branches_left` for the user to delete.
- **task_checks_failed:** the task-wide checks still fail after 2 automatic fix items. Show the user the log it names, and ask whether to add a fix item or stop.

## uncommitted_changes, not_finished, review_needed, checks_failed, not_complete

- **uncommitted_changes:** tracked files changed during the task and no item committed them. Ask the user to commit, stash or undo them, then run `finish`. Do not add an item over them: `plan` refuses that (`dirty_files`).
- **not_finished**, **review_needed:** run `next` and follow it.
- **checks_failed:** a task check fails at `finish`. Add a fix item to `plan.json`, run `plan`, then `next`.
- **not_complete:** `mark` works only after `finish`. Run `finish` first.

## task_stopped, open_questions, handed_back

- **task_stopped**, **open_questions:** the task waits for the user. Do what `next:` says, and only after the user replies.
- **handed_back:** `log wrong_engagement` ended this method on the task. Only `status`, `next`, `resume` and `log` still answer; none of them changes the task's work, and `log` still adds its line to the run record. Carry on as normal work.
- When runs were working in git worktrees at that moment, `log wrong_engagement` and `next` print `worktrees_left`: each worktree folder, with a run's unfinished work in it, and its branch. Nothing removes them. Tell the user where they are and that `git worktree remove --force <worktree>` and `git branch -D <branch>` remove them once nothing in them is wanted. Do not remove them yourself.

## state_unreadable, state_write_failed, record_write_failed, task_locked

These are faults (exit 3). Report them, fix the cause (disk, permissions, another running command), then rerun the same command. Never hand-edit the state files.

A lock whose process has died is taken over by itself, except on Windows. There the script cannot ask whether a process is alive without ending it, so it never takes a lock over. Elsewhere a dead lock can still look alive: another process now has its process id, or the file is damaged. So on every system, if `task_locked` comes back and no other command is running, ask the user, then delete `<T>/.lock` and rerun.

## git_failed, git_missing, commit_failed

- **git_failed**, **git_missing:** report them, then `ad stop --condition fault --detail "<cause>"`. After the fix and the user's reply, `resume`.
- **commit_failed:** usually a pre-commit hook. A failing hook is part of the item's work: fix what it names and rerun `done`.
