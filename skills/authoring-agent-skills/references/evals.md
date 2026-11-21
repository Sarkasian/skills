## Evaluation
- Evals before docs: find gaps → ~3 scenarios → measure the no-skill baseline → write minimal instructions.
- Start with 10–50 cases from real failures.
- **Trigger evals:** ~20 queries, 8–10 should trigger and 8–10 near-miss negatives. Run each 3×; a query passes at trigger rate >0.5. Split 60/40 train/test; ~5 iterations; pick the best by *test* score. Don't paste failed-query keywords into the description (overfits). Simple one-step prompts make poor trigger tests. Cover explicit, implicit, and contextual invocation plus a negative control.
- **Task evals:** with-skill vs without-skill (new skill) or vs the old version (improvement), in the same turn. Report pass rate, tokens, time as mean ± sd with delta. Record tokens and duration immediately (unrecoverable later).
- Prove the skill ran (transcript or host telemetry), and weight that below task quality.
- Graders: code where possible; grade the outcome/environment state, not the final message; LLM judge with an "Unknown" option; partial credit for multi-part tasks; calibrate the judge like a classifier (100–200 labels per failure mode; report TPR/TNR; prefer binary); pairwise for subjective quality; blind comparator for v1 vs v2.
- Error analysis first: open → axial coding, 100+ traces to saturation, one domain-expert "benevolent dictator". Read transcripts; don't trust scores alone.
- pass@k (≥1 of k) for tools; pass^k (all k) for user-facing reliability (75% per run → pass^3 ≈ 42%).
- Capability suite vs regression suite (~100%); graduate saturated tasks into regression. Version datasets and pin them in CI.
- Eval hygiene: a reference solution per task; re-run the reference solutions (they do fail their own tests); clean env per trial (agents read leftover files and git history); a task nobody ever passes is broken; flag assertions that pass with or without the skill, and high-variance cases.
- Efficiency: command count (thrashing), tokens, clean `git status --porcelain`.
- Re-run across model tiers and on new model releases.
- Tooling: check whether a target host ships an eval runner (`references/sources.md`). If none does, run each case in the host's headless mode, or by hand in a fresh session.
```json
{"skill_name":"pdf-forms","evals":[{"id":1,"prompt":"Fill files/w9.pdf from data.json","expected_output":"Filled PDF","files":["evals/files/w9.pdf"],"expectations":["filled.pdf exists","signature_date populated","validate_fields.py ran before write"]}]}
```
```json
[{"query":"fill this vendor W-9 from the CRM export","should_trigger":true},{"query":"summarize this PDF contract","should_trigger":false}]
```
