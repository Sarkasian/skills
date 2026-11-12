# Recovery

Read the section for the error code you got. Each section says who acts and what to run.

## check_failed, item_failed

These go to the executor. Read the log tail in the message and fix the work, then run `done` again. After 3 failed tries the item fails: its files go back to how they were, its last diff is saved under `<T>/patches/`, and work that depends on it fails too. Go on to your next item. The coordinator names failed items in the report, or retries one by editing it in `plan.json` and setting its `status` to `pending`, then running `plan` and `next`.

## check_broken

The check command itself could not run: the command was not found, or the module is missing. It does not use up a try. If the command is wrong, the executor parks the item with `block <id> --question "the check <cmd> is wrong: <why>"`. The coordinator fixes `check_cmd` in `plan.json`, runs `plan`, and the item reruns.

## outside_files, no_changes

**outside_files:** `done` commits only the item's `files`. Undo the edits to the other files. If they belong to a later item in the same run, keep them aside until that item's turn. If the goal really needs another file, ask with `block <id> --approval "change <file>: <why>"`.

**no_changes:** do the goal. If the item truly needs no change, run `done <id> --no-change "<why>"`.

## Stops: needs_user, land_blocked, task_checks_failed

- **needs_user:** questions from executors, or approvals. Ask the user all of them in one message, record the answers, then `resume` (with `--approve` or `--deny` for approvals).
- **land_blocked:** git will not put a finished run's commits on HEAD, because of staged or uncommitted changes in the main folder. Tell the user what git named. Once they commit, unstage or stash it, run `resume`, then `next`.
- A run whose commits clash with work that landed meanwhile does not stop: its items go back to be redone on the current files, and the earlier attempt stays on the branch the note names.
- **task_checks_failed:** the task-wide checks still fail after 2 automatic fix items. Show the user the log it names, and ask whether to add a fix item or stop.

## uncommitted_changes, not_finished, review_needed

- **uncommitted_changes:** tracked files changed during the task that no item committed. If the change belongs to an item, add an item for those files to the plan, then `plan` and `next`. If it is stray, ask the user before anything undoes it.
- **not_finished**, **review_needed:** run `next` and follow it.

## task_stopped, open_questions

The task waits for the user. Do what `next:` says, and only after the user replies.

## state_unreadable, state_write_failed, record_write_failed, task_locked

These are faults (exit 3). Report them, fix the cause (disk, permissions, another running command), then rerun the same command. A lock whose process has died is taken over by itself. Never hand-edit the state files.

## git_failed, git_missing, commit_failed

- **git_failed**, **git_missing:** report them, then `ad stop --condition fault --detail "<cause>"`. After the fix and the user's reply, `resume`.
- **commit_failed:** usually a pre-commit hook. A failing hook is part of the item's work: fix what it names and rerun `done`.
