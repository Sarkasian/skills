## Lesson learning / continuous improvement
- ACE roles: Generator → Reflector (extracts lessons from a trace) → Curator (delta entries) → deterministic code merge.
- Never let an LLM rewrite the whole file. In the ACE paper a full rewrite collapsed a long playbook to a few lines and accuracy fell below the no-playbook baseline. Use grow-and-refine (append + in-place update) with a separate dedup step.
- Resist brevity bias: keep SKILL.md lean and put the detailed playbook in references.
- Learn only from reliable signals (eval failure, validator error, human correction). Self-judged lessons pollute the playbook.
- Locations: team/skill lessons → repo `learnings/proposed/`, agent proposes, human merges via PR; personal → user store, auto-write; org policy → managed, read-only (shared memory is an injection path, so keep it read-only or human-gated).
- Consolidate in the background (scheduled; lookback window = interval), not on the hot path.
- Small index + topic files: hosts load only the head of a memory file. Don't store what's derivable from code or git. Prefer append-only under concurrency.
- Prune when harmful > helpful after N uses, and drop non-discriminating lessons.
```markdown
---
id: L-0042
status: proposed   # proposed|accepted|superseded|pruned
created: YYYY-MM-DD
source: trace://run/abc123
signal: eval_failure   # eval_failure|validator_error|human_correction
helpful: 0
harmful: 0
supersedes: null
---
**Trigger:** … **Lesson:** … **Evidence:** eval X failed 3/3 without, passed 3/3 with. **Action:** add to references/playbook.md §…; add eval case.
```

## Working memory / compaction
- Anything needed after compaction must be in a file the skill tells the agent to re-read. Conversation-only instructions get lost; the always-on file is normally re-read.
- Put critical content first: after compaction some hosts re-attach only the head of each skill.
- Long-running harness: an initializer session creates `init.sh`, `progress.md`, `feature_list.json`, and the first commit. Each session: `pwd` → read progress + `git log` → smoke test → pick ONE item → commit → update progress.
- Status in JSON, not Markdown (less likely to be overwritten); the agent may only flip `passes`.
- "ASSUME INTERRUPTION": view memory first; write after each phase, not at the end.
- Large outputs go to disk, with a path and a short preview in context.
- Clear old tool results first (cheapest win). Clearing invalidates the prompt cache, so clear in large batches, not a little each turn.
- Trimming = deterministic but forgets abruptly; summarization = keeps state but drifts.
- Use a copyable checklist for multi-step skills.
- Handoff block (before compaction, at session end, on subagent return): goal, step N/M, artifact paths (not contents), invariants still in force, last error + what was tried, exact next command.

## Error recovery
- Plan → validate (script, exit 0 required) → fix ONLY the listed items → re-validate (max 3) → apply (idempotent, keyed by change id, applied ids in a state file) → verify → log to progress.
- One structured error format with stable fields:
```
ERROR [field_not_found] Field 'signature_date' not found.
resolves: auto_retry | needs_fix | needs_user | background
next: <exact command>
```
- Errors are actionable (no bare codes or tracebacks); truncation messages steer toward narrower queries; poka-yoke inputs (e.g. absolute paths).
- Git commits = checkpoints; smoke test before new work; resume from the point of failure, don't restart.
- Stop conditions: max iterations, cap on identical failed calls, stop with a stated reason.
- Escalate to the user on: retry cap exceeded, irreversible/financial/sensitive actions (rate each tool low/medium/high risk), or missing input.
- No "done" without end-to-end verification (agents stop at unit tests or curl).
- Scripts distinguish environment/infra failures from input failures.
- Wording: explain why first; use MUST only for invariants that evals show are being violated.
