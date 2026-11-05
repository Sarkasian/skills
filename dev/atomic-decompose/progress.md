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

## Next
- Order change: `report.py` (C-8) is only needed for the release evaluation and weekly metrics, so it is built after the skill body and before the evaluate step, along with its selftest part.
- Evals (DM-6, DM-7), baseline, `SKILL.md`, references, lint, then `report.py`, evaluate, ship.
