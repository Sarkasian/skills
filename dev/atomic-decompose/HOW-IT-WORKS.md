# How atomic-decompose works, and why

This document explains each mechanism of the `atomic-decompose` skill and the reasoning behind its rules. It is written for someone who wants to understand the skill or change it. It does not replace the skill's own files, which are the instructions an agent follows.

## Sources and how to read this document

Every claim cites an id so you can find its source:

- **Charter** (`project documentation/atomic-decompose/atomic-decompose-charter.md` in the `testing` workspace): objectives O-1 to O-6, success criteria SC-x, requirements R-1 and R-2, risks Risk-x.
- **PRD** (`atomic-decompose-charter-prd.md`, same folder): user stories US-1 to US-12 with numbered criteria (US-2.3 is US-2, criterion 3), functional requirements FR-1 to FR-13, non-functional requirements NFR-1 to NFR-11, metrics M-1 to M-9, product risks PR-x.
- **TDD** (`atomic-decompose-tdd.md`, same folder), signed off build-ready on 2026-11-06: components C-x (§2), data models DM-x (§3), interfaces API-x (§4), flows (§5), design decisions DD-1 to DD-26 (§6), technical risks TR-x (§10), open questions and pending PRD amendments PC-x (§11). Walkthrough issues (W-1 to W-4) and closing answers are cited from it and its `atomic-decompose-tdd.gd/` record.
- **Shipped skill** (`skills/atomic-decompose/` in this repository): `SKILL.md`, `references/decomposition.md`, `references/delegation.md` and `scripts/decompose.py`, version 0.1.0.
- **Build log** (`dev/atomic-decompose/progress.md`).

Each section ends with a status line:

- `built`: in the shipped skill today.
- `built, not yet released`: in the TDD and in the skill's working tree, not yet in a release.
- `in the TDD, not yet built`: designed and signed off in the TDD on 2026-11-06, not in the skill. The TDD marks each such rule "not yet built: the build must add this".

Each status line other than `built` cites the TDD units (DD-, API-, DM-) that hold the design.

Where the spec gives no reason for a rule, this document says so rather than supplying one.

## Overview

`atomic-decompose` lets an agent take a substantial or ambiguous task from the user's statement to an accepted result with as little supervision as possible. It plans the task as a pyramid of small work items, asks every question it needs from the user once, each with a default, then works through the items to completion, mostly by delegating them to sub-agents. All task state lives in files in the workspace, managed by a standard-library Python script, so the work survives context compaction and new sessions.

The charter states the problem: agents settle ambiguity by silent assumption, stop at the first workable answer and lose earlier decisions as work grows, so the user's attention becomes the ceiling on what an agent produces (charter §1). The skill serves six objectives (charter §2):

| ID | Objective |
| --- | --- |
| O-1 | Higher leverage: more accepted work per prompt |
| O-2 | Self-sufficient execution: tasks run as long as needed, honour every settled answer, and ask only what only the user can provide |
| O-3 | Criteria-backed best result, with rejected alternatives visible |
| O-4 | Results match intent: ambiguity is resolved against the user's settled scope, never by silent assumption |
| O-5 | Lower token cost per accepted result than the same work without the method |
| O-6 | Harness-agnostic: comparable results on Cursor, Claude Code, Codex, Zoo Code, and Zoo Code with a local 20-70B model |

### The parts

There are two roles. The **coordinator** is the main session's model following `SKILL.md`. It is the only caller of `decompose.py` (TDD §4). An **executor** is a sub-agent, subtask or the main session doing one work item from its brief. An executor never runs the script and never reads `state.json` (TDD §4, API-7). The TDD adds one exception: a chain executor runs `checkpoint`, which writes no task state (API-15, see *Chains*).

The package is a plain skill folder, not a plugin, because every target host reads a `SKILL.md` folder while plugin formats differ per host and Zoo Code has none (DD-1). The TDD planned its own installer (C-6, DD-2). The build replaced it with `npx skills` and `gh skill`, which do the same job (`CHANGELOG.md` 0.1.0; progress.md, 2026-11-04 restructure).

### Where the rules live (DD-3)

`SKILL.md` holds the engagement description and the main workflow. Decomposition guidance is in `references/decomposition.md`, and per-host delegation and reply handling are in `references/delegation.md`. Both are read on demand.

The split exists because NFR-8 caps the instructions loaded before the first work item at 5,000 tokens. `decomposition.md` loads before the first item and counts against that cap. `delegation.md` loads later and does not. Rules the model must never miss, such as the question round, checklist checks and stop conditions, stay in `SKILL.md`, because a model can skip a reference read (DD-3). The rejected options were to put everything in `SKILL.md`, or to keep a minimal `SKILL.md` that points to a reference for every step. The current load is about 4,650 tokens by a characters-divided-by-four estimate (progress.md), so there is little room for new text in the files loaded before the first item.

Status: `built`.

---

## Engagement

**What happens.** The host shows the skill's name and description to its model, which decides whether to load it (API-9). The skill engages on a new task that is ambiguous, has several parts, or needs research, planning or delegation. It also engages when the user asks for it. It does not engage on one edit, one fact or one command, or when the user asks it not to (US-1.1 to US-1.3, FR-12; `SKILL.md`, *Entry*).

It also engages on continuation. If a message or a compaction summary continues or resumes a task saved under `<workspace>/.atomic-decompose/`, the coordinator takes that task folder and runs `handoff` (DD-17). It does not engage on unrelated messages just because a saved task exists.

**Wrong engagement.** If the user says the method should not have engaged, the coordinator runs `log wrong_engagement`. That sets the task to `handed_back`, and the coordinator carries on as normal work (US-1.4, US-1.5). A `handed_back` task is never resumed by the method.

**Why.** US-1 asks that substantial tasks get the method while "simple work stays fast". The risk on the other side is that the method engages on quick tasks and slows them down, so the user turns it off (PR-2, charter Risk-3). Engagement accuracy is gated at release: at least 90% on held-out should-engage cases (NFR-4) and at least 90% on held-out should-not-engage cases (NFR-9). The description is tuned only on the tuning split. The evaluation files are not installed, so the agent under test cannot see the held-out cases (DD-5).

The wrong-engagement mark exists so that over-engagement can be measured in real use: M-5 targets at most 10% of engaged tasks. Continuation engagement exists because some hosts drop the loaded skill body on compaction (DD-17, see *State and run record*). The spec records no rejected options for the engagement conditions themselves. They were set in US-1.

Status: `built`.

## The governing question

**What happens.** At `init`, the coordinator records the user's statement verbatim and one sentence that the final result must answer, the governing question (`SKILL.md` step 1; DM-1). This question is the root of the plan, it appears in every brief under *Place in plan* (API-7), and the first sentence of the result must answer it (US-7.1).

**Why.** The pyramid shape came from the user's direction, "a Minto Pyramid of MECE items" (TDD §5, *Decompose into a pyramid*). MECE means mutually exclusive and collectively exhaustive. A pyramid needs a single apex, and the governing question is that apex. It gives the completeness test for the plan ("every part of the governing question is answered by at least one work item", US-5.2) and the test for the result (answer first, US-7). The spec records no alternatives considered and no further rationale.

Status: `built`.

## The question round

**What happens.** While decomposing, the coordinator looks up every fact a leaf needs in the workspace files, the installed skills and a web search. A fact it finds goes into the leaf's goal or checklist and is never asked. A fact it cannot find becomes a question of one of two types (decomposition.md, *Split* step 3):

- **scope**: what the user wants, such as audience, depth, criteria or thresholds;
- **user-only**: what only the user knows, such as a name, a budget, an owner or a date.

Every question must carry a default the coordinator would act on (`ask --default` is required, and `empty_default` refuses an empty one; API-4). In the first decomposition, every real choice between options that has no settled criteria adds a scope question asking for the criteria (US-6.2).

All unanswered questions then go to the user in **one** message. Each is labelled scope or user-only and shows its default. The coordinator records each reply with `answer --source user`, or `default_accepted` when the user accepts a default without answering (US-2.1 to US-2.3, US-2.6). With nothing to ask, there is no round (US-2.5). Before any question, the coordinator checks `status` and never asks an answered one. If the user says it was already answered, it logs `asked_again` (US-3.2, M-1).

**The rule.** Before any work item starts, every open scope and user-only question goes to the user in one round, and no discoverable question does (FR-11).

**Why.**
- *One round:* "so that I answer once and then leave the method to work" (US-2). After the round, the user is asked nothing until a stop condition (US-4.1). This serves O-2 and O-1, because every extra interruption is a prompt that does not produce work.
- *No discoverable questions:* the user "expects the agent to find everything else" (PRD §2, Delegating user). SC-4.2 wants at least 90% of questions to be ones only the user could answer. NFR-10 allows no discoverable question in the release evaluation, and M-2 allows at most 5% in real use.
- *Two labelled types:* the PRD glossary separates what the task means and how results are judged (scope) from facts about the user (user-only). The run record keeps the type, so the weekly review can check the classification (FR-2; PRD §11, first assumption).
- *Defaults:* a default lets the user accept rather than compose an answer, and it means the method always has something to act on. The known risk is that the user accepts defaults without reading them (PR-1). M-8 watches this: at most 30% of rounds should have every default accepted unanswered.

**Questions after the round.** A scope question raised by a result goes back to the user, because the scope is the user's (TDD §5, *Scope change*, user-decided). A scope answer re-expands every node that is not done. Mid-task user-only questions are asked together, after the work they do not block (US-4.2, US-4.3).

The shipped skill finishes the work a scope question does not block before it stops. The TDD instead dispatches nothing new, handles the replies of running items, then stops (closing answer f3-9). The shipped option was rejected because the re-plan re-expands only nodes that are not done, so work finished meanwhile would be locked in under the old scope. Mid-task scope questions are pending PRD amendment PC-13 (§11).

The spec records no rejected options for the question round as a whole. Its shape is set by the PRD.

Status: `built`. The stop on a mid-task scope question without finishing other work is `built, not yet released` (§5 *Scope change*, API-4).

### Starting unblocked items while questions are open

**What happens (DD-26).** Items that need no answer start before the opening round, each briefed to a background sub-agent, only when a blocking question tool is available in the session and the host or mode can run an executor while the question is open. Interactive Cursor qualifies; headless runs, Zoo Code and main-session mode put the round first (§5 *Question round* step 1). `next` holds back any leaf needing an unanswered question, and the opening round stays round 1 (API-4, API-5).

On a new-session entry the coordinator holds each `running` item whose executor was lost (reason `executor lost with the previous session`), which restores its files and makes a late reply `stale_attempt`. It skips the item a `needs_approval` stop names, and its later chain steps, because their executor is not lost but waiting for the user (§5 *Compaction and resume* step 3, user decision). If an answer makes a `done` early item unneeded, the coordinator reverses its patch and runs `drop --unneeded`, which keeps it out of the result (API-3; user decision, no rejected options recorded).

**Why.** The options were to start early wherever the host can (the earlier decision), to start early only with a blocking question tool and hold lost items, or always to ask first. The user chose the second (closing answers q2 and f5-10). Early items stayed `running` once a headless turn or session ended, so `finish` refused with `open_items` (closing walkthrough). Always asking first gives up the saving where it works. The test is the tool, not the host, because the coordinator can see the tool. The costs: a still-live in-place executor can edit after the restore, and a held item's work is wasted. The early start is pending PRD amendments PC-4 and PC-5 (see *Open proposals*).

Status: `built, not yet released` (DD-26; API-3 `drop --unneeded`, API-4 `asked`, API-5 `next`). The released `SKILL.md` runs the question round (step 3) before execution (step 4).

## Decomposition into a pyramid

**What happens.** The coordinator splits the governing question into 2 to 7 children. No two children may produce the same deliverable, and together they must cover every part of their parent. Each child is then tested (next section): it becomes a leaf, a group that is split again, or a deferred group. A node with more than 7 children gets an extra grouping level (decomposition.md, *Split*). Each node is added with one `add` call, parents before children, and `validate` must print `"ok": true` before the question round (`SKILL.md` step 2).

`validate` reports these problems (API-3): `childless_group`, `duplicate_title`, `cycle` (including a leaf that depends on its own ancestor group), `dangling_dependency` (a dependency on a dropped item), and `open_question`. Titles must be unique even against dropped items, so a replacement always takes a new title.

**The rules.**
- No overlap and nothing missing: FR-9, US-5.2.
- At most 7 children per node: DD-13.

**Why.**
- *No overlap, nothing missing (FR-9):* overlapping items would do the same work twice and could produce conflicting answers. A gap would leave part of the governing question unanswered. US-5.2 makes both visible to the user when they ask for the plan.
- *At most 7 (DD-13):* the options were at most 5, at most 7, and no cap. The user chose 7. The stated reason is that a parent small enough to check for overlap and gaps keeps FR-9 checkable. The cost is deeper trees for wide tasks.
- *At least 2:* the shipped text says 2 to 7, but the spec gives no rationale for the lower bound.
- *Unique titles:* the title is the deliverable (DM-2). Duplicate titles would hide overlap. The spec gives no reason why dropped titles also count. In practice it makes a replacement item clearly distinct from the item it replaces in the run record.

Status: `built`.

## What counts as atomic: the leaf test

**What happens.** A child is a leaf when all of these hold (decomposition.md, *Split* step 2; TDD §5, *Decompose* step 2):

- it has one deliverable;
- it has a checklist whose every entry a reader can check from the result alone;
- it has one return format;
- one executor can do it without asking anything.

A leaf takes `--goal`, at least one `--check` and `--returns`. `add` refuses a leaf without them (`leaf_without_goal`, `leaf_without_checklist`, `leaf_without_returns`; API-3).

**Why.** Each condition supports another requirement. FR-9 asks for work items "that each have their own completion checklist and run as one work item". FR-4 requires every result to be checked against its checklist before the task uses it, which is only possible if the checklist can be judged from the result file alone. FR-3 requires that an executor "needs nothing from the conversation history", which is what "without asking anything" tests. The spec does not record alternatives to this test.

Status: `built`.

### Atomic items and chains

DD-20 keeps atomic items as the unit of **planning and checking**, but no longer as the unit of **execution**. See *Combined execution: batches and chains*.

## Groups, deferred groups and discovery leaves

**What happens.** A child that can be split now becomes a group and is split again. A child that cannot be split until something is known becomes a **deferred group** with no children. Beside it, never inside it, the coordinator adds a **discovery leaf** whose goal is to find that out, with `--discovers <group id>` (decomposition.md, *Split* step 2).

When the discovery leaf is done, `next` lists the group in `expand`. The coordinator then adds its children, or drops it if there is nothing to add and names it in the result. If the discovery leaf fails or is dropped, the script drops the still-childless group itself (API-5, DD-17). `finish` refuses while a group is listed in `expand` (`open_items`, API-2).

Re-entry into decomposition also happens when a result contradicts the plan (re-expand the contradicted nodes), when a scope answer arrives (re-expand every node not done), and when an item fails for good (drop its pending dependants) (decomposition.md, *Re-entry*).

**Why (DD-10).** The options were to plan the whole pyramid before any work starts, or to plan in rolling waves. Rolling waves were proposed by the assistant and accepted by the user. A discovery result can change what the rest of the plan should be, so a full plan made before it is guesswork that then has to be re-planned. The cost is that the plan is incomplete at the start, and the plan the user sees shows a deferred group with its discovery leaf (US-5.2).

*Beside, not inside:* a blind review found that a discovery leaf placed inside its own group hid the deferred work. `add` now refuses this with `not_deferrable` (progress.md, High 1).

*`expand` rather than automatic dropping:* `next` lists a childless group whose discovery is done instead of dropping it, "so the coordinator decides" (DD-17).

Status: `built`.

## Needs, and how they are inherited

**What happens.** Each item records in `--needs` the questions whose answers it uses. The script keeps every item's `needs` a superset of the `needs` of everything in its `depends_on`. It adds them on `add` and again when `complete --verdict blocked` adds a question (API-3). A dependency on a group means all of the group's non-dropped leaves (API-3). `blocked_by` is always derived: it is the user-only questions in `needs` that have no answer (API-5).

**Why.** "so an answer change reaches every item built on it" (API-3). When the user changes an answer, the script resets every item whose `needs` hold that question (API-4). Without inheritance, an item that built on another item's result would keep the old answer's consequences. Inherited needs also mean the brief carries every settled answer the item depends on, even indirectly (TDD §5, *Guarantee: settled answers hold*). The spec records no alternatives.

Status: `built`.

## Scheduling priority

**What happens.** `next` returns ready batches in this order: batches holding a discovery leaf first, then by the number of pending items whose dependency chain reaches the batch (most first), then by lowest id, compared segment by segment as integers so `1.10` comes after `1.9` (API-5).

**Why (DD-11).** The options were plain id order, longest critical path first, and this order. The assistant proposed this order and the user accepted it. Discovery first unblocks the deferred groups of DD-10 soonest. Counting pending dependants is "a simple stand-in for the critical path that needs no time estimates". DD-11 accepts that this is not an optimal schedule.

Status: `built`.

## Parallel caps

**What happens.** The coordinator runs at once up to the lower of the task's `max_parallel` and the host's cap, minus the batches still running (`SKILL.md` step 4.3). `max_parallel` is the lower of the user's configured value (default 4) and the named profile's cap, fixed for the task at `init` (DM-1, DM-9). The host caps are recorded in `delegation.md`:

| Host | Cap | Source in DD-18 |
| --- | --- | --- |
| Cursor | none | Several Task calls run at once, and no limit is documented |
| Claude Code | 20 | Its concurrent subagent limit |
| Codex | 6 | Default `agents.max_threads` |
| Zoo Code | 1 | A parent task awaits one child |
| Main session | 1 | — |

Replies are handled one at a time as they arrive. Before any stop, nothing new is dispatched and the replies of running batches are handled first, so no item other than the one stopped on is running while the task is stopped (TDD §5, *Execute* step 1).

**Why (DD-18).** The options were one batch at a time, every ready batch at once, and a user maximum lowered to the host and model cap. The user chose the capped maximum. One at a time wastes hosts that can run several. Every ready batch at once ignores host limits and the user's token budget. The stated trade-off is that parallel executors cost tokens at the same time (Cursor: five in parallel use about five times the tokens). A host cap set lower than its default is the user's to mirror in `max_parallel`.

The model's own cap lives in a profile because the script cannot tell which model runs it (DD-15).

Status: `built`.

## Combined execution: batches and chains

### Batching small siblings

**What happens.** Leaves share one brief and one executor only when all of these hold (DD-14, API-5):

- they have the same parent;
- each is marked `small`;
- there is no dependency between them, and none is a discovery leaf;
- they use the same skill, or none;
- each is on its first attempt;
- there are at most `max_batch` of them (default 4).

In a batch, each item keeps its own `ITEM` block, checklist, result path, reply entry and verdict. The planner judges `small`, and the script checks the rest.

DD-14 defines `small` as no web search or research, no workspace change, and a whole result that fits within the 150-word summary. The shipped `decomposition.md` describes it more loosely ("a lookup, one small file or one short section"). Anyone tightening the planner's judgement should reconcile the two. The TDD makes `add` refuse `--small` with `--writes` (`bad_input`), so `next` never batches writes items (API-3, walkthrough W-2; `built, not yet released`).

**Why (DD-14).** The options were one delegation per leaf, batching every small sibling, and batching under these rules. The user chose these rules. The stated reasons:

- Every sub-agent re-pays a fixed prefix of system prompt, tool schemas and brief, often 10,000 to 30,000 tokens, and over-investing in simple subtasks is a common failure.
- Published batching results show large token savings, but accuracy fell sharply at 6 items per batch, while 3 or 4 often did well. Longer inputs degrade more (Cheng et al., EMNLP 2023).
- Reliability falls as input grows, and topically related distractors hurt most. Siblings are related by design, so batches stay short and a retry runs alone.
- Batching shares only the delegation, so items stay atomic.

The default of 4 is marked as a `ponytail:` simplification. It comes from batched question answering and research agents, not from this setting, and the release evaluation is meant to confirm or tune it per model (DD-14).

**`max_batch` profiles (DD-15).** The options were one value edited when the model changes, an `init` flag only, and named profiles. The user chose named profiles, because the right batch size differs per model and the script cannot tell which model runs it. The precedence, highest first, is `init --profile`, `<workspace>/.atomic-decompose/config.local.json`, `<workspace>/.atomic-decompose/config.json`, `~/.config/atomic-decompose/config.json`, then the default. Configuration lives outside the installed folder. Environment variables are not used, because hosts do not reliably pass them to the shell. The resolved value is stored in the task, so a task keeps one batch size.

Status: `built`.

### Chains

**What happens.** Work is still broken down to atomic items. Each item keeps its own checklist, verdict and run-record line, so FR-9, FR-4 and M-4 keep their meaning. Related items are then combined into a **chain** for execution: one executor does them in order without re-reading context.

Items can be steps of one chain only if all of these hold:

- they depend on each other;
- they read and change largely the same files;
- no result between them could change the plan;
- no approval gate sits between them;
- they use the same skill, or none.

The planner adds each later step with `add --chain-after <id>` and judges the files, plan and gate conditions; the script checks the rest and the length cap `max_chain`, else `chain_invalid` (API-14). The executor stops at the first step that fails or replies `BLOCKED`, `APPROVAL` or `SKILL_FAILED`. That step uses one DD-12 attempt; later, unrun steps return to `pending` without one (`held`, `chain stopped at <id>`).

**Checkpoint refs (API-14, API-15).** A chain's writes steps share one working tree. After each writes step the executor runs `checkpoint <step-id>`, which writes only a ref ending `-end`; the next step starts from it, and each step's patch, `changes` and `verify` cover its own span, so each step is still checked alone. `checkpoint` writes no task state, so the script stays its single writer (DD-8), and the suffix keeps the ref apart from the `brief` checkpoint.

Batches (independent small siblings, DD-14) and chains (dependent steps) are the two kinds of combined execution unit. "Task" keeps its meaning: the user's whole request.

**Why (DD-20).** The first real run, on 2026-11-05, split a brief into 8 items that formed one dependency chain through one 2,000-line file. Each executor re-read the file, and only 2 items ever ran in parallel. The principle drawn from it is that a boundary between executors is worth its cost only where it gives parallelism, context isolation, a result that could change the plan, or a user or risk gate. The user chose chains over one delegation per leaf (built), which pays every boundary, and over merging the leaves into one item, which would lose the per-item checklist, retry and failure count that FR-4, FR-9 and M-4 rest on. `max_chain` defaults to 5 (user decision, a `ponytail:` starting value tuned per profile, DD-15). The costs: one executor holds every step's context, and the planner's judgement is unchecked. Chains are pending PRD amendments PC-2 and PC-9 (§11).

Status: `built, not yet released` (DD-20; API-14, API-15; DM-9 `max_chain`).

### Leaves that change the same file

**What happens (DD-22).** Leaves that will change the same file, with no logical dependency, are ordered with `--depends` and chained within `max_chain`, else run one after another, never in parallel worktrees (§5 *Decompose* step 5).

**Why.** The assistant proposed this and the user accepted it. It reuses `--chain-after` with no new flag, and in walkthrough W-4 it avoids 2 to 3 likely clashes, each costing an attempt and another read of a 1,891-line file. Parallel worktrees (built) pay those clashes as the normal case. Declaring files at `add` needs a new flag and `next` rule and reverses an earlier user decision. Main-session mode for the whole plan gives up parallelism where no file is shared. The costs: the ordering link is an ordinary dependency, so a failed first leaf drops the second (PC-11, §11), and an overlap the planner misses falls back to `patch_conflict`.

Status: `built, not yet released` (DD-22; API-3, API-14).

## Briefs

**What happens.** `brief <ids>` prints the text the coordinator passes **unchanged** as the executor's whole prompt (`SKILL.md` step 4.3, API-7). For each item it holds:

- the item id, attempt number and title;
- the goal;
- its place in the plan: the governing question and each ancestor's title;
- the settled answers it needs (its inherited `needs`);
- the settled decisions it must follow: those on the item, its ancestors, or any item its dependency chain reaches;
- the results it builds on: each dependency's summary and result path;
- the skill path, or none;
- the completion checklist and return format;
- after a fail or a hold, the reason;
- the absolute path for its result file.

It ends with reply rules: ask the user nothing; reply `BLOCKED` for a fact only the user knows; reply `APPROVAL` instead of taking a step outside the goal; reply `SKILL_FAILED` if the skill does not load; do not edit `state.json`. `brief` also sets the items `running` and counts the attempt.

**The rule.** FR-3: each delegated work item receives its goal, its place in the plan, the settled answers it needs, a completion checklist and the expected return format, and needs nothing from the conversation history.

**Why.**
- *Script-rendered brief:* the script renders it so the model spends no tokens assembling state (DD-6).
- *Passed unchanged:* the coordinator cannot leave out or mis-paraphrase a settled answer. US-3.1 requires every later work item to stay consistent with settled answers.
- *Nothing else:* the executor gets no conversation history, no other item's full result and no `state.json` (API-7). This is context isolation, and it keeps the brief small (NFR-3).
- *Decisions on the nearest common ancestor:* a decision later items in other branches must follow is recorded on their nearest common ancestor, so it reaches every brief below it (TDD §5, *Execute* step 9).

The spec records no alternatives to the brief format.

Status: `built`. The `Edits:` line is `built, not yet released` (DD-8, API-7). Evidence pointers, the list of script-run commands and the `Outside this item:` line (submodules and sparse-checkout files are not restored) are `built, not yet released` (API-7, DD-23).

## Replies and checking results against checklists

**What happens.** An executor writes each item's full result to its result path and ends with one line per item (API-8; delegation.md, *Replies*):

- `RESULT <id> <attempt> <path>` plus a summary of at most 150 words. The coordinator reads the result file and judges every checklist entry against it, and checks it against the settled answers and decisions in the brief. A missing file, a missing or failed entry, or a contradiction is a fail. A pass is recorded with the result path and summary.
- `BLOCKED <id> <attempt> <question>`. The coordinator first looks the fact up. If found, it records a fail with the fact as the reason, so the retry carries it. If not, it asks a user-only question and records `blocked`, and other work goes on.
- `APPROVAL <id> <attempt> <step>`. The item stays running, the task stops `needs_approval`, and the user's reply goes into the next brief as a `held` reason.
- `SKILL_FAILED <id> <attempt> <skill>`. Recorded as `held`, then handled as a fault.
- No entry, or a missing result path, is a fail.

The attempt number echoes the item's `briefs` counter, which never resets. `complete` refuses a reply from a superseded brief (`stale_attempt`) or for an item no longer running (`not_running`), and the coordinator discards it (API-5). After every pass, the coordinator asks what the result changed: a discovery, a contradiction of the plan, or a new scope question (delegation.md).

**The rule.** FR-4: every work item's result is checked against its completion checklist before the task uses it.

**Why.** PR-4 names the risk: a result looks complete but misses what was needed, because an item passed without doing the work. The release evaluation plants weak delegated results (FR-7, DM-6 `weak_result`) and requires those cases to pass. Checking against settled answers and decisions serves US-3.1. The 150-word summary keeps the coordinator's context small (NFR-3, API-8), because later briefs carry the summary and point to the full result. `briefs` is separate from `attempts` so that a reply from an old brief can always be recognised, even after an answer change resets `attempts` to 0 (DM-2, glossary *Attempt*).

Status: `built`.

### Script-run checks and evidence pointers

**What happens (DD-23).** A checklist entry a command can check is added with `add --check-cmd`: one shell line that passes on exit 0, with relative paths and no `cd`, since the script picks the tree (API-3). After a reply, the coordinator runs `verify <id>`, which runs every command entry in the item's working tree, each for at most `check_timeout_s` (a profile setting, default 600 seconds; a timeout is a failure), and records the exit codes (API-5). `complete --verdict pass` is refused with `checks_not_passed` unless `verify` of that attempt recorded every code as 0. For each judgement entry the executor gives a `CHECK <id> <n> <path>:<line>` pointer (API-8). The coordinator reads the codes and the pointed lines, and the result file only when a pointer is in doubt.

**Why.** The user chose this (their earlier open proposal) over the result file alone (built), which lets "tests pass" rest on the executor's word and filled the coordinator's context until it compacted (W-2 to W-4), and over reading the changed files or the patch, which puts their text in that context and breaks the rule that no model reads a patch (DM-11). A recorded exit code cannot be misreported, and a pointer costs a few lines. The costs: the host approves the one script call, not each command, so its per-command rules do not apply (§10); and a judgement entry still rests on a pointer.

Status: `built, not yet released` (DD-23; API-3 `--check-cmd`, API-5 `verify` and `checks_not_passed`, API-8, DM-9 `check_timeout_s`).

## Retries

**What happens.** A failed result goes back to `pending`, and the next brief carries the failure reason. The third failed attempt marks the item `failed` (`RETRY_LIMIT = 2` in `decompose.py`). `complete` then prints its `dependants`, the coordinator drops each with `--cause` the failed item, and other work carries on (US-4.4; delegation.md). `blocked` and `held` take the attempt back, so they do not count toward the limit (API-5).

**Why (DD-12).** The options were 1, 2 and 3 retries. The user chose 2. Each retry brief carries the failure reason, so a second retry still has new information, while a third mostly repeats the cost. A result that needs four attempts ends `failed`, which M-4 counts (at most 5% of items).

*Dropping dependants:* a blind review found that a failed item's dependants were never dropped, so the loop could never finish. `complete` now reports them (progress.md, High 2).

*Taking attempts back:* the spec does not state a reason. The effect is that a question to the user, or waiting for approval, is not counted as the executor failing.

Under the TDD, a failing check command is a fail too (DD-23), and in a chain only the stopping step uses an attempt (DD-20).

Status: `built`.

## Handoff of file changes

### As shipped in 0.1.0 (the earlier DD-8 choice)

**What happens.** Executors never change workspace files. They put each change in the result file as a unified diff with `a/` and `b/` paths. After the checklist passes, the coordinator does three things. First, it checks that the item is still running at the reply's attempt. Second, it stops for approval if the diff deletes files or changes anything outside the plan the user saw. Third, it runs `git apply --check` and then `git apply`. A diff that does not apply changes nothing, is recorded as a fail and is retried against the current files (delegation.md, *Diffs*; API-8).

**Why (earlier DD-8).** Against executors writing directly, whole replacement files, and diffs applied by the script's own code, the user first chose diffs with `git apply`: writes stay single-threaded; direct writers could overwrite each other and leave nothing to reverse; whole files cost the full file for a one-line change; and `git apply --check` tests a short diff whole before any file changes. Items were not declared by file, because the files an item edits seemed unknown at planning time.

### Current design (DD-8)

**What happens.**

1. Executors never copy files. They read the originals.
2. The planner marks items that change workspace files with `add --writes`.
3. **In place.** A writes item runs in place when no other writes item is running. The script records a git checkpoint of the whole working tree, including uncommitted and untracked files, under a hidden ref, without touching the user's index, branch or stash list. On fail, blocked or held it restores only the changed paths. On pass it saves a git-generated patch. While an in-place item runs, other writes items wait.
4. **In parallel.** Writes items that are ready together run in parallel, each in a detached git worktree under the task folder. On pass the script applies the worktree's patch. A clash is `patch_conflict`: nothing changes, and the item retries against the current files.
5. Main-session mode uses the in-place path.
6. The task folder writes a `.gitignore` of `*`, so it never appears in `git status`.
7. Hidden refs and worktrees are removed when the task is accepted, and under the TDD also at `finish` (DD-25, see *The task folder*).
8. Writes items require `git` and a git repository, else the task stops with the fault `git_missing`, `not_a_git_repo` or `git_failed` (DD-16). Under the TDD, a writes item's `brief` also refuses with `git_failed`, before any change, while a git operation is in progress (merge, rebase, cherry-pick, revert, `am` or bisect) or in a bare repository (API-1, API-5). The user settled this open point of §3 and widened it to all six operations; no rejected option or reason is recorded. Its effect is that no checkpoint is taken mid-operation.

**Why (DD-8).** The user chose "in place when alone, else a worktree" on 2026-11-05, after the first real run. One writer of task state remains; a checkpoint restores exactly the paths an attempt changed; no model reads a diff, which removes the first run's malformed diffs (DM-11); and the first run's whole-folder copy of 584 untracked files is gone. A worktree for every item was rejected because it lacks ignored files such as `node_modules` that tests may need, and in place for every item because it gives up parallel writes items (DD-18). The costs: a restore puts back every changed path, so a user edit made during an in-place run is lost, and two crash and late-edit windows are accepted (§11, *Known limitations*).

**Patch format (DD-21).** The saved patch is `git diff --binary --full-index --no-renames --no-ext-diff --no-textconv --no-color`, applied after `git apply --check` and reversed with `git apply -R`. Plain `git diff` was rejected because it writes binary changes as unappliable lines, and the flags keep the user's rename, diff-driver and text-filter settings out. Commits were rejected because they change the user's history, and file copies because they cost the whole file. The costs: binary patches are as large as the files, and every rename stops for approval as a delete and an add.

Status: `built, not yet released` (DD-8, DD-21; API-5, DM-2, DM-11). The refusal of in-progress operations and bare repositories is `built, not yet released` (API-1, API-5 `brief`).

### The plan the user saw

**What happens.** The question-round message, or a notice that asks nothing when there are no questions, shows each leaf and the files each writes item may change. The coordinator logs it with `log plan_shown`, where a path ending `/` covers everything under it (API-2), and logs again after a re-plan adds writes items. Before a writes item passes, `changes <id>` lists its files and, under `unlisted`, those the last `plan_shown` entry does not cover; a deleted file or any `unlisted` path stops `needs_approval` (API-5).

**Why.** Walkthroughs W-3 and W-4 found "the plan the user saw" (US-4.5) undefined, since the round showed only questions. The user chose a run-record entry over an `add` field, with no reason recorded. The trailing-`/` rule fills the closing walkthrough's gap for directories (closing answer q3), and `unlisted` spares the coordinator reading `record.jsonl` (DD-17). A notice shown again mid-task is pending PRD amendment PC-15.

Status: `built, not yet released` (API-2 `log plan_shown`, API-5 `changes`, DM-5).

## Reversal after an answer change

**What happens.** When the user changes a settled answer, `answer` resets every running, done or failed item whose `needs` hold the question to `pending`, with attempts at 0, and sets a `complete` task back to `active`. It prints `affected`, with each item's previous status in `was` (API-4). The coordinator then:

- discards any reply from a brief sent before the change (`not_running`, `stale_attempt`);
- reverses the changes of items whose `was` is `done`, latest first, in the reverse order of their last `item_done` lines in `record.jsonl`;
- re-adds, under new titles, the items that were dropped because a now-reset item had failed;
- continues execution.

The result names the affected items (US-3.4, US-3.5; `SKILL.md`, *Changed answer*).

As shipped, reversal runs `git apply -R --check`, then `git apply -R`. A diff that does not reverse cleanly stops for approval. On approval, `git apply -R --reject` reverses what it can and leaves `.rej` files, which are named in the result (delegation.md, *Reversing*). Under the current handoff, reversal reverses the saved patches, latest first (DD-8, DD-21).

The TDD adds a step before `answer`: dispatch nothing new and handle running replies, so no executor is still editing when `answer` restores a running writes item's files (§5 *Change a settled answer* step 1, API-4, user-decided).

**Why.** Latest first, "so a later diff on the same lines comes off before the one it was applied on" (TDD §5, *Change a settled answer* step 2). The runnable check asserts that earliest first fails and latest first succeeds (TDD §8). Reversibility was one of DD-8's reasons for single-writer diffs. The spec records no alternative reversal strategies.

Status: `built` for the diff-based reversal. Reversal of saved patches is `built, not yet released` (DD-8, DD-21). The step before `answer` is `built, not yet released` (API-4).

## State and run record

**What happens.**
- `state.json` holds the task's state (DM-1): statement, governing question, mode, status, items, questions with answers, decisions, batch and parallel limits. It is rewritten whole and atomically on every change.
- `record.jsonl` is an append-only run record (DM-5) with one line per state change. Every line has a monotonic `seq`, a per-invocation `cmd` id, and the invocation's arguments on its first line.
- Every write appends the record line first, then replaces the state.
- Every writing command holds `<task>/.lock`, created exclusively, for the length of the command (API-1).

**Single writer.** Only the coordinator runs the script (TDD §4).

**Stateless coordinator.** The coordinator starts every step from script output (`next`, `status`, or `handoff` on entry), never from memory (`SKILL.md` first paragraph). After a compaction summary it runs `log compaction` and then `handoff`. In a new session it runs `resume` and then `handoff`, and follows the printed next command.

**Why a script (DD-6).** The options were a plan file the model writes itself, SQLite through `sqlite3`, a third-party tool, an MCP server, and a standard-library script. A script validates every change and renders briefs, so the model spends no tokens rewriting state. A model-written file has no validation. SQLite is binary, so neither the model nor the user can read or diff it. A third-party tool adds a dependency. With a shell and no authentication, a command-line tool plus a skill often beats an MCP server. The cost is a dependency on `python3` on every host (TR-1).

**Why a state file plus a record (DD-7).** The options were one event log replayed on every read, a state file with no record, or both. Both were chosen: a read is one file parse, where a replayed log costs more with every event, and FR-2 needs the record, which a state file alone would lose on each rewrite. FR-2 lists what the record must hold, because the metrics read it.

**Why a per-command lock (DD-16).** A lock held for one command stops lost updates without limiting how many work items run at once. A session-long lock would limit them, and no lock allows silent lost updates.

**Why stateless (DD-17).** The options were to detect compaction and reload the skill, to rely on the host re-attaching the skill after compaction, or to keep the coordinator stateless. The user chose stateless. Detecting and reloading fails because Codex and Zoo Code drop the loaded skill body on compaction, and with it the instruction to detect. Relying on re-attachment fails because only Claude Code re-attaches skills. With a stateless coordinator, a new or compacted agent restarts by loading the skill and running `handoff`. This is what makes US-3.3 hold on long runs and on local models with small contexts (US-10.2, NFR-5, M-1).

Status: `built`.

## Faults

**What happens.** A script command that exits 3 is a fault. The coordinator stops, reports the error's message and its `next` step, and runs only what the *Faults* table in `SKILL.md` allows:

| Error | Action |
| --- | --- |
| `state_write_failed` | Nothing. `resume` re-applies the change later. |
| `state_unreadable` | Nothing. Report the cause. |
| `record_write_failed` | `stop --condition fault` once. |
| `record_torn` | `resume`, which truncates the torn line, then carry on with no stop. |
| `task_locked` | Nothing. The user deletes the lock only when no other session is working on the task. |
| Missing `git`, missing skill, `SKILL_FAILED` | `stop --condition fault`, naming the cause. |

A tool that fails inside a work item is not a fault. It is a work-item failure, handled by retries (US-4.1).

**The rule.** FR-8: detect unreadable saved state, a failed read or write of saved state, and a missing skill. On any of them, stop, report the cause and next step, and do not overwrite saved state.

**Why.**
- *The three PRD faults:* they protect US-3. A method that overwrote unreadable state would silently lose settled answers.
- *The wider set (DD-16):* FR-8 left the remaining cases to the TDD as a named open decision. The user rejected a state hash in each record line (it would stop on every hand edit, and FR-8 excludes detecting outside edits), a session-long lock (it limits parallel work), no lock (lost updates), migrating other versions (not done, so another version's task cannot resume), and marking unapplied lines by timestamp (a clock set back could hide or repeat a line, so `seq` is used).
- *Record first:* because the record line is written first, a torn last line belongs to an invocation the state never received, so truncating it leaves the state consistent. `resume` re-applies an invocation whose first line survived, and reports a lost change as `torn_line`.
- *An unapplied `brief`:* it printed no brief, so `resume` lists its items as `undelivered` instead of re-applying it.
- *The cost:* a crash while holding the lock leaves the lock behind, so `task_locked` names the file to delete.

Status: `built`.

## Main-session mode

**What happens.** `init --mode main_session` runs every item in the main session. The coordinator does each item itself from the same brief, with the same checklist and return format, then handles its own reply. The parallel cap is 1. Delegation can also be refused per brief: `brief --mode main_session`, or, if the host refuses a brief already printed, the coordinator does the item from that same brief (delegation.md, *Your host*; API-10).

**The rule.** FR-5: the method can be set, on any host, to run work items in the main session. On a host without delegation, or when so set, items run in the main session with the same checklists and return formats.

**Why (DD-9).** The options were an environment variable, a setting in the configuration file, and an `init` flag with a per-brief override. The flag with the override was chosen. The user asks for the mode in the request. A configuration setting is a standing preference, while the mode belongs to one task. Hosts do not reliably pass environment variables to the shell. The cost is that there is no global default other than delegation. NFR-11 holds main-session results to within 10 points of delegated Cursor results, and US-12.2 runs every case this way on Cursor.

Under the current handoff, main-session mode uses the in-place path.

### One-entry plans

**What happens.** A plan that is one `next` entry from the start (one leaf, one batch or one chain) runs in the main session, unless the user asked for delegation, which `init --mode delegate` records as explicit (DM-1 `mode_explicit`). `next` reports `one_entry`, true only while the plan has been one entry from the start, so a plan that had more entries delegates its last one too (API-5).

**Why (DD-9).** The assistant proposed the rule and the user accepted it. A one-entry plan has nothing to run in parallel or isolate, so delegating it only adds a 10,000 to 30,000-token sub-agent prefix (W-1). User-set only (built) keeps paying that prefix, and a plan-size threshold in the configuration makes the user guess a size per task. "From the start" fixes the closing finding that `one_entry` turned true at every plan's last entry (closing answer q1). The costs: a one-entry task loses context isolation, and NFR-11 then compares main session with main session (PC-10). A `delegate_baseline` run tests the saving (API-12).

Status: `built` for the mode flag and per-brief override. The in-place handoff for main-session mode is `built, not yet released` (DD-8). The one-entry rule and `init --mode delegate` as an explicit request are `built, not yet released` (DD-9; API-2 `init`, API-5 `next`, DM-1 `mode_explicit`).

## Skill routing

**What happens.** When an installed skill's description fits an item, the planner passes its absolute `SKILL.md` path as `add --skill`. The path is taken from the host's own listing (delegation.md, *Skill paths*):

| Host | Where the path comes from |
| --- | --- |
| Codex | The `(file: <path>)` entry, with any root alias such as `r0` expanded |
| Cursor | The `fullPath`, with any alias such as `$0` expanded |
| Zoo Code | `<location>` |
| Claude Code | `<workspace>/.claude/skills/<name>/SKILL.md`, else `~/.claude/skills/<name>/SKILL.md` |

The script refuses a path that is not absolute (`skill_path_not_absolute`) or does not exist (`skill_missing`), checks it again at `brief`, and prints it in the brief. A batch shares one skill or none. The result names each skill used with its items, and any matching skill that could not be routed (US-8.2). An item with no fitting skill runs without one, which is not a fault (US-8.3).

**The rule.** FR-13: a work item uses an installed skill whose description matches it.

**Why (DD-19).** The options were a skill name searched in a fixed list of skill folders, or the path the host lists. The user chose the listed path. Hosts also list plugin and system skills from folders outside any fixed list, so a name search fails on skills the model can see. Claude Code lists names and descriptions only, so there the path is built from its two skill folders. The cost is that a Claude Code plugin skill cannot be routed. Its item runs without the skill and is named in the result.

Status: `built`.

## Stops and approvals

**What happens.** After the question round, the method asks the user nothing until it reaches a stop condition (US-4.1):

- the task is complete;
- every remaining item is blocked by a user-only question (`blocked_on_user`);
- a step needs approval (`needs_approval`);
- a fault;
- the user asks it to stop (`user_stop`).

On a stop, the coordinator tells the user which condition it stopped on and what it needs to continue (US-4.6). Before deleting files, contacting a third party or making any change the user did not see in the plan, it stops and asks (US-4.5). Executors reply `APPROVAL` instead of taking such a step.

**Why.** US-4 asks that the user "can look away for as long as the task needs" (O-2). Approval for steps outside the plan is the other side of that promise: the user agreed to the plan, not to unseen side effects. M-3 measures tasks whose final stop is not completion, with a target of at most 10%. The spec records no alternatives.

Status: `built`.

## Choices between options

**What happens.** When a step has more than one viable option, the coordinator compares the options against the settled criteria. If no criteria cover the choice, it states default criteria, records them as a scope question answered `default_unconfirmed`, and lists them in the result for the user to confirm. It records the outcome with `decide`: the chosen option and each rejected option with why it lost (`SKILL.md`, *Choices*; US-6). `decide` refuses a decision with no rejected option (`no_rejected_option`).

**Why.** O-3 asks for the best option against the user's criteria, with every rejected alternative visible. Criteria for choices known at planning time go into the question round (US-6.2). Choices found later use stated defaults, so work does not stop, and the defaults are surfaced at the end (US-6.4, US-6.5). SC-3.1 audits a sample of results against an independent review of the option space.

Status: `built`.

## The result and marks

**What happens.** After `finish` and `status`, the coordinator writes the result (`SKILL.md` step 5):

1. The first sentence answers the governing question.
2. Supporting points follow, grouped under the top-level items.
3. Each decision: the chosen option, each rejected option and why it lost.
4. Each skill used, with its items, and any matching skill that could not be routed.
5. Last: failed and dropped items, items a changed answer affected, and every `default_unconfirmed` answer, with a request to confirm each.

If the user accepts, the coordinator runs `mark accepted`, which also removes any checkpoint refs and worktrees still left (DD-25; `built, not yet released`). If the user asks for rework, it runs `mark reworked --reason`, re-plans from the reason and continues with the same settled answers. If the user does neither, nothing is written, and the task counts as unmarked, not accepted (US-11). Token totals are logged at `finish` and at every stop when the host exposes them, and are otherwise marked unavailable (FR-2).

**Why.** US-7: "so that I can accept or reject it at a glance". Failures and unconfirmed defaults come after the answer (US-7.3), but they are always listed, so nothing is silently assumed (O-4). The marks exist because every success criterion counts accepted results. SC-1.1 is accepted tasks per prompt, and M-7 is the share sent back for rework, with a target of at most 10%. An unmarked result is not counted as accepted so that the metric cannot be inflated by silence (US-11.4). Rework continues the same task so that settled answers hold (US-11.3, US-3).

Status: `built`.

### Final check at finish

**What happens (DD-24).** `finish` reruns, in the workspace, the check commands of every passed writes item (DD-23). If one fails it changes nothing and reports `checks_failed`, whose `next:` line adds one fix leaf holding the failing commands and depending on nothing new; the `done` item stays as it is. `finish` skips a failing command that any `failed` leaf also holds, listing it as unresolved, so a failed fix leaf ends the loop (API-2). An end-condition command therefore goes on the writes leaf that completes the condition, not on a separate check leaf (§5 *Decompose* step 5, user decision).

**Why.** Each worktree patch passed alone, so a check can break once the patches are combined (W-4). The user chose the rerun because it costs no model tokens and reuses DD-23's commands. Doing nothing (built) leaves the end condition to the planner's memory. A fresh sub-agent review of the whole diff (the user's earlier open proposal) costs a sub-agent prefix plus the diff. A check leaf depending on every writes leaf relies on the planner adding it. For the skip rule (closing answer of 2026-11-06, option c), skipping only the fix leaf's commands was rejected because the script cannot tell the fix leaf from other failed leaves, and marking it needs a new flag and field. The costs: an unrelated failed leaf sharing a command such as `pytest` lets `finish` complete over it, listed as unresolved; and a command finds no clash in meaning between items.

Status: `built, not yet released` (DD-24; API-2 `finish` and `checks_failed`).

## The task folder

**What happens.** Each engaged task gets `<workspace>/.atomic-decompose/<task-id>/`. The id is the UTC date plus a slug of the governing question (API-2). The folder holds:

| File | Kept |
| --- | --- |
| `state.json` | Until the user deletes the folder (DM-1) |
| `record.jsonl` | Until the user deletes the folder |
| `results/<id>.md` | Until the user deletes the folder |
| `.lock` | Only while a command runs. A crash can leave it behind (DD-16). |
| `patches/<id>.patch` | Until the user deletes the folder (DM-11) |
| `wt/<id>` | A writes item's worktree, removed at its pass or restore, and at `finish` or acceptance (DD-25) |
| `.gitignore` (`*`) | Until the user deletes the folder (DM-1) |

Optional configuration files sit beside the task folders in `.atomic-decompose/` (DM-9). As shipped in 0.1.0, nothing edits `.gitignore`, and the README asks the user to add `.atomic-decompose/` to it (TDD §9, *First run*). Under the current design the task folder ignores itself, with no edit to the user's `.gitignore` (DD-4).

**Why (DD-4).** The options were a folder under the user's home, a folder inside a host's own directory (`.roo/`, `.codex/`), the system temp folder, and a workspace folder of its own, which was chosen:

- FR-1 resumes in the same workspace.
- The Codex `workspace-write` sandbox keeps writes inside the workspace and `.codex` read-only, which rules out the home folder and `.codex/`.
- Zoo Code asks for approval for writes under `.roo/`.
- Temp folders do not survive a new session.

The costs are that the folder still shows in the user's file tree, and that a task cannot move between workspaces.

### When refs and worktrees are deleted

**What happens (DD-25).** A task's hidden refs and worktrees are deleted at `finish`, once the rerun passes and no item runs, as well as at `mark accepted`. State, record, results and patches stay (API-2).

**Why.** The assistant proposed "also at `finish`" and the user accepted it. After `finish` no item needs a checkpoint, and a changed answer reverses patches, not refs. At acceptance only (built), an unmarked or abandoned task keeps refs in the user's repository indefinitely (W-3). Per-item deletion at `complete` needs chain-aware rules, since a later step starts from the previous `-end` ref. The `ponytail:` cost is that a task that never reaches `finish` keeps its refs; per-item deletion is the upgrade path.

Status: `built` for the folder and the first four files in the table. The `.gitignore`, patches, worktrees and clean-up at acceptance are `built, not yet released` (DD-4, DD-8, DM-11). Clean-up at `finish` is `built, not yet released` (DD-25; API-2 `finish`).

## Metrics and the release evaluation

**What happens.** The skill is released only after evaluations covering O-1 to O-5 pass with it and outperform the same evaluations without it (charter R-2). The evaluation suite holds:

- task cases with scripted answers and checkable expectations;
- engagement cases split into held-out and tuning sets by a stable hash (FR-7, DM-6, DM-7).

Each task case runs once with and once without the method on each target harness. On Cursor it also runs once in main-session mode. Held-out engagement cases run with the method only (US-12.1, US-12.2). The project halts if, across hosted harnesses, tokens per passing result with the method exceed twice the ratio without it (charter §11, exit criterion 2; US-12.5, US-12.13).

Release targets, all proposed by the assistant for the sponsor's review (PRD §5):

| ID | Target |
| --- | --- |
| NFR-1 | At least 90% of pooled expectations met with the method, on Cursor |
| NFR-2 | At least 20 points more than without the method, on Cursor |
| NFR-3 | Tokens per expectation met at most 100% of the without-method ratio, on Cursor |
| NFR-4 | At least 90% of held-out should-engage cases engage, per harness |
| NFR-5 | No settled answer contradicted or asked again in the long-run case |
| NFR-6 | Every planted question asked |
| NFR-7 | Each harness within 10 points of Cursor |
| NFR-8 | At most 5,000 tokens loaded before the first work item |
| NFR-9 | At least 90% of held-out should-not-engage cases stay out, per harness |
| NFR-10 | No discoverable question asked |
| NFR-11 | Main-session mode within 10 points of delegated Cursor |

Weekly metrics in the 30 days after release, read from run records and a weekly session review (PRD §8):

| ID | Metric | Target |
| --- | --- | --- |
| M-1 | Settled answers asked again or contradicted, per task | 0 |
| M-2 | Questions that were discoverable | At most 5% |
| M-3 | Tasks whose final stop is not completion | At most 10% |
| M-4 | Items that fail after retries | At most 5% |
| M-5 | Wrong engagements | At most 10% |
| M-6 | Tokens spent before the first work item | At most 15% |
| M-7 | Marked results sent back for rework | At most 10% |
| M-8 | Rounds where every default was accepted unanswered | At most 30% |
| M-9 | Tokens per accepted result | At most 80% of the without-method comparator |

**Why.** The charter makes the release evaluation-gated because the method's overhead could cost more than it returns (Risk-1, Risk-2). The weekly metrics watch real use against the specific failure modes the mechanisms above are meant to prevent: re-asking (M-1), discoverable questions (M-2), stalls (M-3), weak items (M-4), over-engagement (M-5), up-front cost (M-6), scope misses (M-7), and rubber-stamped defaults (M-8). The many counting rules (charter §3, PRD §8 and §9) exist so that baseline and window cover the same task class and tokens are attributed to the right task on each host.

For changes, note that M-4 counts distinct failed leaf items (TDD §5, *Execute*). This is one reason DD-20 keeps atomic items as the unit of checking: a chain step is its own leaf, so chaining does not change what M-4 counts.

Status: `built` for the evaluation cases: 8 task cases in `evals/evals.json` and 52 engagement cases in `evals/trigger_evals.json` (progress.md, 2026-11-04). The report script (C-8, `report.py`) is `built, not yet released` for Cursor only: its token totals wait for the Cursor usage-export columns, and the other harnesses' parts are not built (progress.md, 2026-11-06). Separately, the baseline run without the skill is blocked on a Cursor CLI login (progress.md, *Done* and *Next*).

---

## Open proposals

These two ideas have **not** been decided; both are open questions in TDD §11. Each motive is inferred from the first real run. The other earlier proposals were decided: thin checking became DD-23, the whole-diff review lost to the check rerun (DD-24), mode by plan shape became DD-9, and chains DD-20.

**Briefs with a git-derived list of earlier changes and one-line inherited answers** (§11, API-7, NFR-3).
- *Proposal:* a brief lists the earlier changes to the files an item touches, derived from git, and shows each inherited answer in one line.
- *Motive:* in the first run, each executor re-read a large file. Telling it what earlier items changed could narrow what it needs to read. Shorter inherited answers would shrink every brief (NFR-3).

**Automated deletion of temporary files at set stages** (§11, DM-1, DD-25).
- *Proposal:* per-item scratch is deleted at item completion, results at acceptance, and state and record are pruned after the metrics have read them.
- *Motive:* apart from refs and worktrees (DD-25), everything is kept until the user deletes the folder (DM-1). A deletion schedule must not remove anything FR-1 resume, a changed answer's reversal, or the weekly metrics (FR-2, M-1 to M-9) still need.

### Pending before and during the build

- **PRD amendments.** 15 PRD conflicts (PC-1 to PC-15) are pending an authorised PRD amendment (TDD §11), among them the git faults, the early start, chains, one-entry plans and mid-task scope questions.
- **Deferred closing findings.** The closing review's six findings, F1 to F6 (five Medium, one Low), were deferred to the build with no further reopens (user decision 2026-11-06, in the TDD's `.gd/closing.result.json`). All concern the DD-26 early start: which file holds its test (F1), a test wording that names a host (F2), checking its prediction (F3), how a `needs_approval` stop names its item (F4), Claude Code's background mode (F5), and collecting background replies (F6).
