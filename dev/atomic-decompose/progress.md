# atomic-decompose build log

Spec: `project documentation/atomic-decompose/atomic-decompose-tdd.md` (build-ready 2026-11-04). Plan: `~/.cursor/plans/atomic_decomposition_skill_5738b57e.plan.md`.

## Restart path
1. Read this file, then the plan's todo list.
2. `python3 dev/atomic-decompose/selftest.py` from the repo root must exit 0 before any new work.

## Decisions during the build
- Order changed from evals-first: `scripts/decompose.py` was written first while the §3/§4 spec was loaded; evals follow before the skill body, and the baseline run (without the skill) still precedes writing `SKILL.md`, so only observed gaps go into it.
- Deferred closing Low (API-12): apply "when another harness is verified that week and no other M-9 unmeasured rule applies" to the mid-week-harness clause when writing `report.py`.

## Done
- 2026-11-04: scaffolded (plain skill, no plugin) with `authoring-agent-skills/scripts/scaffold.py`.
- 2026-11-04: `scripts/decompose.py` (C-4): all API-1 to API-8 commands; smoke-tested init/ask/asked/answer/add/validate/next/brief/complete/handoff.

- 2026-11-04: `selftest.py` C-4 and C-6 parts pass (`python3 selftest.py`). Mutation check: setting `RETRY_LIMIT = 3` or string-sorting ids makes it fail. Fixes made while testing: `validate` treats a group's children as edges, so a leaf depending on its own ancestor is a `cycle`; `next` batching no longer requires an empty `depends_on` (DD-14 only forbids depends between batch members, which readiness already excludes); `resume` reads a `brief`'s ids through the parser.
- 2026-11-04: `install.py` (C-6): ownership is a `.installed-by-atomic-decompose` stamp in the installed folder; the Claude Code symlink is ours when it points at that folder.
- Notes: `validate` `duplicate_title` can only fire on edited state, because `add` already refuses any existing title (dropped included), so the selftest edits `state.json` for it.

- 2026-11-04: evals. `evals/evals.json` has 8 DM-6 task cases (choice + new session + accept; weak result + rework; 12-module long run with plan follow-ups; no-question rename; all defaults accepted + answer change; approval + two owner questions; `csv-profile` skill route; wrong engagement). Fixtures are under `evals/files/<case>/`. Q2 2026 sales total 909,892 and Q3 952,511 come from the seeded generator. `evals/trigger_evals.json` has 52 DM-7 cases; the held-out split is 11 engage and 10 stay out.
- 2026-11-04: `SKILL.md` (C-2), `references/decomposition.md` and `references/delegation.md` (C-3) written from TDD §5. `lint_skill.py --portable`: 0 errors. Accepted warning: "decompose.py has no --dry-run". Its job is to record state, and `validate`, `next`, `status` and `handoff` are its read-only commands. Load size is about 4,400 tokens (chars/4) for all three files, against the NFR-8 limit of 5,000. The description was trimmed to 386 characters.
- Blocked: the baseline run without the skill. `cursor-agent` 2026.01.28 is installed but not logged in (`cursor-agent status`), so pauln has to run `cursor-agent login`.
- Risk: the long-run case may not compact on large-context hosts; on Zoo Code with a local model it will.

- 2026-11-04: blind review of the skill text against the script and TDD §5 found 2 High and 7 Medium issues; all fixed.
  - High 1: a discovery leaf placed inside its own group hid the deferred work. The text now says "beside", and `add` refuses it with `not_deferrable`.
  - High 2: a failed item's dependants were never dropped, so the loop could not finish. `complete` now prints `dependants` when an item fails, and delegation.md drops them.
  - Medium fixes: Faults-table precedence over `next:`; the compaction folder choice uses the latest `updated_at`; the parallel cap counts running batches; reply-discard wording; delegation refused after `brief`; affected items read from `status`; and a reset discovery leaf is dropped.
  - Additive output changes beyond TDD API-5 and API-6 (keys added, none changed): `complete` gains `dependants`; `status` items gain `kind`, `needs` and `depends_on`; `status` answers gain `changed_at`. These belong in the TDD at its next revision.
  - Load size is now about 4,650 tokens (chars/4), close to the NFR-8 limit of 5,000. Measure with each harness's tokenizer (`load_tokens.json`) before release.
- 2026-11-04: two learnings proposed in `authoring-agent-skills/learnings/proposed/`: L-0001 (config layout for a plain skill) and L-0002 (per-model values through profiles).

- 2026-11-04: restructured for a multi-skill repo, staged at `/home/pauln/projects/testing/skills-repo/` for pauln to copy into a new GitHub repo. The package is in `skills/atomic-decompose/` (the only folder installers copy); the development files are in `dev/atomic-decompose/`. `install.py` is deleted, because `npx skills add` and `gh skill install` do the same job (one copy in `.agents/skills/` plus a Claude Code link). TDD revision item: C-6 and API-11 become "install with `npx skills` or `gh skill`", the without-method arm runs `npx skills remove`, and the §8 C-6 assertions are dropped from `selftest.py`. The fixture skill is renamed `SKILL.fixture.md` under `evals/files/fixture-skills/`, so installers that scan for `SKILL.md` don't offer it. Paths earlier in this log refer to the old `testing/atomic-decompose/` folder.

- 2026-11-05: replaced the hand-written-diff handoff with git-managed changes (user-approved design). Why: the first real run produced 584 untracked copied files (executors copied the workspace to make diffs), one malformed hand-written diff, and diff text flooding the coordinator's context. What changed:
  - `decompose.py`: `add --writes`; `brief` checkpoints the working tree with a temporary `GIT_INDEX_FILE` (`read-tree HEAD`, `add -A`, `write-tree`, `commit-tree`) to `refs/atomic-decompose/<task-id>/<id>-<attempt>`, in place for a lone writer, else `git worktree add --detach <task>/wt/<id>`; `next` holds writers while an in-place one runs; `complete` pass saves `patches/<id>.patch` (`git diff --binary --full-index`), applying a worktree's patch after `git apply --check` (`patch_conflict`, exit 1, otherwise); fail/blocked/held and `answer` restore by reverse-applying the attempt's own diff, or remove the worktree; new read-only `changes`; `init` writes `<task>/.gitignore`; `mark accepted` removes refs and worktrees; `resume` replays skip git side effects (`Writer.replay`).
  - Docs: delegation.md *Diffs* became *Workspace changes* (approval check via `changes`, user-does-not-edit assumption, ignored files absent from worktrees); *Replies*, *Approvals*, *Reversing* updated; decomposition.md documents `--writes`; SKILL.md *Changed answer* and *Faults* rows; README requirements.
  - `selftest.py`: the coordinator-diff test is replaced by four git tests (in-place checkpoint/restore/pass, hold and worktrees with clash and cleanup, reversal from patches, non-repo and missing git). Mutation checks (hold off, restore off, `.gitignore` off, ref cleanup off, look-ahead off, `read-tree` off, worktree apply off, clash check off, `patch` field not stored) each fail it.
  - Load size: SKILL.md + decomposition.md + delegation.md = 19,636 chars, about 4,910 tokens (chars/4), under NFR-8's 5,000 (was about 4,650).
  - TDD revision items: DD-4 (the task folder ignores itself via `<task>/.gitignore`; the user's `.gitignore` still untouched); DD-8 (git checkpoints and patches replace executor diffs); a new decision for checkpoints vs worktrees (in place for a lone writer, worktrees for writers ready together, `next` holds writers behind an in-place one, user does not edit the same files meanwhile); API-3 `add --writes`; API-5 (`brief` checkpoint/worktree, `next` hold, `complete` patch/restore and `patch_conflict`, `changes` command, `answer` `affected[].patch`, `status` fields, `mark accepted` cleanup, `not_a_git_repo`/`git_missing`/`git_failed`); API-7 `Edits:` line and reply rules; API-8 (no diff in result files; approval check on the patch's file list); DM-2 fields `writes`, `checkpoint`, `worktree`, `patch`; DM-5 `item_started`/`item_done`/`item_retried`/`item_failed`/`item_blocked`/`item_held`/`marked` data; §5 delegation flows (*Execute work items*, *Change a settled answer*, approvals); §8 runnable-check assertions; DD-16 (`git` faults and replay without side effects); §9 first run (no `.gitignore` advice).
  - Report: `dev/atomic-decompose/handoff-change-report.md`.

- 2026-11-06: built the TDD's "not yet built" items (signed off `build-ready` the same day), by hand without the implementation loop.
  - `decompose.py`:
    - `init`: `mode_explicit`, `max_chain`, `check_timeout_s` (DM-1, DM-9).
    - `add`: `--check-cmd` and `--chain-after` (`chain_invalid`); refuses `--small --writes`.
    - `blocked_by` includes scope questions; `asked` round numbering (round 1 first).
    - `brief`: git-operation and bare-repository refusal, the chain's shared tree, the new brief lines.
    - New commands `verify` (runs before the lock; the process group is killed on timeout; `resume` re-applies its codes from the `checks_run` line without rerunning) and `checkpoint` (API-15, no state write).
    - `complete`: `checks_not_passed`; chain spans for the patch, restore and unrun steps.
    - `changes` `unlisted`; `log plan_shown` (must list every non-dropped writes item); `drop --unneeded` (`patch_not_reversed`).
    - `finish`: rerun, `checks_failed`, skip rule, clean-up.
    - `next` `one_entry`; `answer_changed` `affected`; a re-applied fail sets `worktree` null.
  - Small design choices the TDD leaves open:
    - `add --chain-after` also refuses a second next step after the same leaf, so a chain never branches.
    - `brief` refuses a later chain step whose earlier step is neither done nor in the same brief.
    - The checkpoint goes on the first writes step of a chain brief, and a later step's start is the previous writes step's `-end` ref.
    - `verify` reports a failure as exit 1 `checks_failed`, printing its JSON first.
    - `log plan_shown` refuses a line missing a writes item (`bad_input`).
  - Coordinator text:
    - `SKILL.md`: the new-session hold (DD-26), start-early, the plan notice and `plan_shown`, `one_entry`, the scope-question stop, `finish` `checks_failed`, fault re-runs.
    - `decomposition.md`: `--check-cmd`, `--chain-after`, same-file ordering, end-condition commands, re-logging the plan after a re-plan adds writes items.
    - `delegation.md`: the status check, `verify` and `CHECK` pointers, *Chains*, `unlisted`, background executors.
    - Closing findings F4 (the `needs_approval` detail names the item), F5 (start-early written for any host with a blocking question tool) and F6 (collect background replies after the round) are handled. F1–F3 are TDD §2/§8/§9 wording, left for the next TDD revision.
  - Verification:
    - `python3 dev/atomic-decompose/selftest.py`: all assertions hold. Two old assertions changed with the design: the round-2 numbering, and refs removed at `finish` rather than at `mark accepted`.
    - Mutation check: 12 single-line breaks (scope blocking, `one_entry`, skip rule, unrun step, `finish` clean-up, `checks_not_passed`, process-group kill, `unlisted`, chain-as-one-writer, git-operation refusal, shared-worktree keep, `affected`) each fail the selftest.
    - `lint_skill.py --portable`: 0 errors, the same three accepted warnings.
  - Load size (NFR-8 counts `SKILL.md` and `decomposition.md` only; DD-3 excludes `delegation.md`, read at delegation): 16,449 chars, about 4,110 tokens (chars/4). Earlier entries counted `delegation.md` too; on that basis the total is now 25,246 chars, about 6,310 tokens.
  - Not built: C-8 `report.py`, including API-12's `delegate_baseline` arm (DM-8). It was never built; see *Next*.

## 2026-11-06 — C-8 `report.py`, Cursor only
- Scope (pauln, 2026-11-06): only Cursor is tested for now, and nothing for the other harnesses is built.
  - No host token parsers: Codex rollouts, Claude Code results and OTLP, and Zoo Code are all left out.
  - Cursor token parsing waits until an export of pauln's account pins the usage-export columns (PRD §12). Every token total is null, so NFR-3 (when neither arm meets zero expectations) and the exit-criterion-2 ratio are `not_computable`, and `pr6.escalate` is true. `--cursor-export` is accepted but not read.
  - `score_trigger_evals.py` is not run. NFR-4 and NFR-9 are computed in `report.py` with the same held-out hash.
  - `weekly` has no `--sessions` flag. M-6 and M-9 are `unmeasured` for each non-Cursor `--roots` harness, and there is no Cursor entry. The M-9 comparator and the deferred M-9 mid-week Low (above) wait until M-9 is built.
- Built, `dev/atomic-decompose/report.py`:
  - `release`:
    - all PRD §5 targets that need no tokens: NFR-1, 2, 4 to 11, plus NFR-3's two by-definition cases;
    - the gate;
    - exit criterion 2, by definition when either arm has no pass, else `not_computable`, with `exit_criterion_2_missing` naming tokens and attribution;
    - `criterion_10_runs` and the setup faults;
    - `delegate_baseline`, kept out of every pool;
    - `trigger_runs.jsonl`, `report.json`, and `report.md` (per-expectation pass/fail, models, the PR-4 escalation line);
    - `case_mismatch` and `bad_run_line`.
  - `weekly`: M-1 to M-5, M-7 and M-8, pooled across harnesses; M-1 and M-2 use the DM-10 marks, with null marks left out; tasks whose DM-1 is unreadable or whose record is torn are listed as gaps, and gaps above 10% make the week `incomplete`; a missing marks file makes M-1 and M-2 `unmeasured`; `marks_unreadable`; writes `<marks>/<week>.json`.
  - Choices: M-2 counts each asked question once per task. A zero denominator gives value null and status `incomplete`. M-8 leaves out rounds with an unanswered question.
- Verification: `python3 dev/atomic-decompose/selftest.py` passes (new `test_report_release`, `test_report_weekly`). Mutation check: 12 single-line breaks in `report.py` each fail the selftest. The first pass missed three of them (the held-out hash, NFR-3 by definition, user stops in M-3), and assertions were added for each.

## Next
- Cursor token parsing in `report.py`, once pauln downloads a usage export and its columns are confirmed (PRD §12).
- Baseline run (blocked on `cursor-agent login`), evaluate, ship.
