# Changelog

## 1.4.0 (2026-11-27)

Fixes from an audit of 1.3.0. The task evals and trigger evals have not been re-run; they need a headless agent CLI.

Lint (`lint_skill.py`):
- Change calls. The lint now knows two groups. Local changes: `os.remove`, `os.replace`, `shutil.rmtree`, `shutil.move`, `rm` in a shell line or an argument list, `git merge`, `git clean`, `git reset --hard`. Changes outside the machine or repository: `git push` (also as an argument list), `requests.post` and the like, `method="POST|PUT|PATCH|DELETE"`, `smtplib`, `curl -X`, `kubectl` and `terraform` apply or delete, `DROP TABLE`, `DELETE FROM`, `TRUNCATE`, `npm publish`, `cargo publish`, `twine upload`, `gh pr merge`, `docker push`, `aws s3 rm`. It is still a text check and does not know every form.
- `--dry-run` counts only where the script defines or tests the flag (`add_argument("--dry-run")`, a shell `case` branch, a comparison, `argv`). A mention in a string or a trailing comment no longer counts.
- Waiver. `lint: no-dry-run: <reason>` must be a comment, on its own line or after code, with a reason of three words or more. A string literal does not waive. The waiver is still per file and covers local changes only; a change outside the machine is reported with or without it.
- Scripts scan. Skipped: `node_modules`, `venv`, `vendor`, `third_party`, `__pycache__`, `fixtures`, `dist`, `build` and any folder whose name starts with a dot. Test files (`test_*`, `selftest`, anything under `tests/`) get no `--dry-run` warning. A symlink or a special file is named in a warning and not read.
- Interactive check. `input(` is checked in `.py` files only and not inside a docstring. New: `getpass.getpass(` and shell `read -rp` or `read -r -p`.
- Paths. A `#fragment`, a link title and a trailing `?`, `!`, `*`, `]`, `}`, `|` or `>` are no longer part of a path. A path in bold, behind a `${...SKILL...}/` variable or written with a backslash is now checked. Paths named inside `references/*.md` are checked too. A bare path whose folder the skill does not have is a warning (it may be a path in the user's project); a Markdown link, or a path in a folder the skill has, stays an error.
- One level deep. The warning now fires when a reference names an `.md` file that SKILL.md does not name, in either link form. A reference that names a file SKILL.md also names is allowed.
- Description. Third-person verbs ("Deploys", "Publishes") now match the side-effect check, and words after "Not for" do not. The hint no longer names one host's frontmatter key. "I/O" is no longer read as first person. An XML or HTML tag is a warning.
- Frontmatter. A UTF-8 byte order mark is accepted. A YAML comment after an unquoted value is dropped. Escapes in a double-quoted value are decoded before the length is counted. `compatibility` over 500 characters is an error.
- Body. A 499-line body with a final newline was counted as 500; it is now 499. A `TODO` left in SKILL.md is a warning.
- Eval files. `evals.json` must be an object with an `evals` array. Each trigger entry needs a string `query` and a true or false `should_trigger`.
- Exit codes. 2 now also means the lint could not run: `--evals-dir` is not a folder, or a file is unreadable or not UTF-8. The message goes to stderr and nothing to stdout. Deeply nested JSON is a lint error. No file is read past 1,000,000 characters.

Other scripts:
- `scaffold.py`: a description with a control character (a newline, for example) is refused with exit 2. The description is escaped once, in a form valid in both JSON and a double-quoted YAML value, so backslashes and quotes survive. A destination that is a symlink or lies under one is refused, also with `--force`. A target that cannot be written is exit 2 with a one-line message.
- `score_trigger_evals.py`: `should_trigger` and `triggered` must be JSON true or false and `query` a string. A line of the wrong shape, a file that is not UTF-8, a file with no runs and two runs of one query with different `should_trigger` are exit 2.
- `assets/redirect-skill.md`: the host-specific `user-invocable` key is replaced by a comment, so the template passes `--portable`.

Guidance:
- `references/authoring.md`: the waiver text matches the lint. Dependencies are "the standard library alone, or inline script metadata with pinned package versions", and a split script keeps the entry script's rule. Removed the clause about content in the middle of a long context, which had no listed source.
- `references/decide.md`: a script that changes things needs `--dry-run`; the `--confirm` requirement is gone. "One level deep" is defined as: SKILL.md names each reference.
- `references/evals.md`: at least 3 cases to start, growing towards 10 to 50. Both arms of a task eval start together, each in its own clean run.
- `references/ship.md` and step 9: a plain skill holds the version in `metadata.version`; a plugin holds the same string in every manifest too.
- `references/sources.md`: the sentence on Vercel's evals says only that wording changed the results. It was not re-read for this release.
- `references/runtime.md`: the example path `references/playbook.md` is now `references/<topic>.md`, because the lint checks paths in references.
- SKILL.md: step 7 explains exit code 2. New gotcha: check the scaffolded plugin manifests against each host's manifest reference.

Evals and tests:
- Eval 4 now asks for a skill ("Make a skill so that we always run ruff before committing"). The old prompt asked for a rule, which the trigger evals say must not load this skill. Its recorded results below are for the old prompt.
- New eval 6 with the fixture `evals/files/fixture-skills/notes-keeper/`, a skill that sits at its own 20-line cap. It checks the size-limit rule from 1.3.0. Learning L-0002 records that rule.
- `selftest.py` has an assertion for each change above. A run of 27 single-line mutants of the scripts: 7 failed the 1.3.0 selftest, all 27 fail this one. The assertion on `scripts/notes.py` now puts a real call in a comment; before, it could not fail.

Not tested:
- Task evals 1 to 6 and the trigger evals, with this version.
- Windows.
- The plugin manifest templates and the URLs in `references/sources.md` against the hosts' current documentation (no network).
- No release tag was made.

## 1.3.0 (2026-11-27)

New guidance for a file that reaches its size limit. The evals have not been re-run for it.
- `references/authoring.md`, "When a file reaches its size limit": move situational text from SKILL.md to `references/` with a load condition; do not cap a script's lines, and split a long one into modules behind the same entry script; never delete instructions, argument help, tests or doc sentences to pass a size check; ask before a limit moves.
- Step 5 has one hard rule that says the same.
- `lint_skill.py` checks scripts in subfolders of `scripts/` too (side effects without `--dry-run`, interactive prompts), so splitting a script into modules does not hide it from the lint. Only a script directly in `scripts/` needs its own `--help`.
- A comment `lint: no-dry-run: <reason>` in a script turns off the "no `--dry-run` flag" warning for that file. The reason is required. `references/authoring.md` says when to use it.
- Signal: an agent editing `atomic-decompose` met the SKILL.md and script caps by cutting the "never commit or revert" and "never approve for the user" rules, argument help and blank lines.

## 1.2.1 (2026-11-21)
Tuned from the first eval run (the entry below this one's results list).
- Description rewritten from the train failures only: leads with "creates, fixes and reviews", names a skill that is not picked up and a procedure the agent is told again and again, and excludes using an existing skill and product documents about skills. Trigger evals, 21 queries × 3 runs: train 0.692 → 0.846 (11 of 13), test 0.875 → 1.0 (8 of 8). No false triggers. Still failing: the two implicit train queries with no "skill" in them, which the host's built-in `create-rule` takes.
- Step 2: a credential, live data or writes to a service point to an MCP server first, with an env-token script as the stated fallback; "always / never / every time" gets a rule and a hook. `references/decide.md` says why (the credential stays out of the agent's shell and transcript).
- New review-only path under the checklist: lint, check against steps 2, 3, 5 and 9, report each finding with its file, line or lint message, change no files.
- Task evals 1, 3 and 4 re-run with the skill, one run each: eval 1 3/3 (was 2/3; the decision names MCP as preferred and falls back to a script because no Jira MCP server was available), eval 3 5/5 with no files changed (was 5/5 with the skill rewritten), eval 4 3/3 (was 2/3; rule and hook created). With evals 2 and 5 unchanged from the first run that is 18 of 18 with the skill against 11 of 18 without. Same limits as below: single runs, model "Auto", one machine.

## Eval tooling and first eval run for 1.2.0 (2026-11-21)
- New `dev/authoring-agent-skills/run_evals.py`: runs the trigger evals and the task evals in a headless agent CLI. Built against the Cursor CLI (`cursor-agent`); it is a development tool and is not part of the installed skill. `selftest.py` checks its task mode with a stub agent.
- First recorded eval run for 1.2.0 (2026-11-21, Cursor CLI 2026.11.19, model "Auto", one machine):
  - Trigger evals, 21 queries × 3 runs, no failed runs: train pass rate 0.692 (9 of 13), test 0.875 (7 of 8). Four positive queries lost to the host's built-in `create-skill` or `create-rule` skill; "Write a PRD for the skills marketplace feature" triggered 3 of 3 and should not. The description is not changed yet.
  - Task evals, one run per arm, graded by hand: with the skill 16 of 18 expectations, without 11 of 18. Eval 1: 2/3 vs 2/3 (with the skill the agent chose a script over an MCP server). Eval 2: 3/3 vs 1/3. Eval 3: 5/5 vs 3/5. Eval 4: 2/3 vs 2/3 (neither arm added or recommended a hook). Eval 5: 4/4 vs 3/4.
  - Limits of these numbers: one run per arm; the model is whatever "Auto" picked; the agent sees every skill installed on the machine, so trigger results differ between machines; the eval 5 baseline read another installed skill's config code and this repository's notes, so its 3/4 is too high; in eval 3 the with-skill agent rewrote the skill when asked only to review it. With-skill runs took 210 to 245 s against 50 to 140 s without.
  - The "11/11 with, 7/11 without" figure in the 1.0.1 entry was not reproduced.

## 1.2.0 (2026-11-21)
- References no longer store host-specific facts: frontmatter keys, folder paths, size limits, CLI commands, settings and manifest fields, telemetry event names, model benchmark scores, dated product plans and study figures are removed. Each file keeps the principle and says what to look up.
- `references/sources.md` is now "Finding current facts": the steps to look a fact up and confirm it, and a table of topic → documentation page → what to look up. All 50 URLs in it returned HTTP 200 on 2026-11-21. SKILL.md tells the agent to use it whenever a step needs a host-specific fact, and step 10 reports the facts left unverified.
- Section numbers and "(added)" marks from the lost source page are gone from the reference headings.
- `references/ship.md`: configuration for a plain skill (layered config outside the skill folder), from learning L-0001, now accepted with eval 5. `references/authoring.md`: when to keep `evals/` and `learnings/` in the skill folder and when to move them to `dev/<name>/`.
- Lint: warns on a reference file SKILL.md never names. The side-effect check looks for calls that change things (`shutil.rmtree`, `git push`, `requests.post`, …), not words such as "send", and ignores comment lines. The interactive check catches every `input(` call, not only one with a literal prompt.
- Eval 2 expects the user-invoked-only switch of each target host, looked up; it expected one host's frontmatter key.
- SKILL.md frontmatter: `license: MIT`.
- Not run: task evals and trigger evals. The references lost most of their host detail in this version, so a with-skill run of evals 1 to 5 is the check that nothing needed went with it.

## 1.1.0 (2026-11-21)
- Lint: a `references/`, `scripts/` or `assets/` path is checked wherever it appears, so a missing script named inside a command (`python3 scripts/x.py`) is now an error. Before, only a path directly after a backtick was checked.
- Lint: new `--evals-dir DIR` for repositories that keep evals outside the skill folder.
- Lint: a `trigger_evals.json` that is not an array of objects is reported as an error; it used to raise a traceback.
- Scaffold: the new skill gets `assets/learning-entry.md`, which its `learnings/README.md` names. The "files exist" error goes to stderr.
- References: `ship.md` now holds configuration, versioning and security. Telemetry, deprecation and distribution moved to the new `distribute.md`, which step 9 loads only when needed.
- References are edited by hand from now on. The page they were generated from is lost, so `sync_references.py` and the "generated, do not edit" headers are removed.
- SKILL.md: the 5k-token compaction limit is described as the behaviour of some hosts. Removed a dated claim from the distribution reference.
- Eval 3 reviews a fixture skill, `evals/files/fixture-skills/changelog-writer/`, with planted defects; `selftest.py` checks the linter finds each one.
- Trigger evals: three queries added (two positive, one negative) that the description was never tuned on. The 1.0.1 description fix added words close to a failed query, which the skill's own rule forbids, so the 18/18 figure below is not a held-out score.
- Not run: task evals and trigger evals. Re-run the trigger evals and record the train and test pass rates before changing the description again.

## 1.0.2 (2026-11-21)
- Packaged for this repository: the skill is in `skills/authoring-agent-skills/`; evals, learnings, `selftest.py` and `sync_references.py` are in `dev/authoring-agent-skills/`.
- Commands use `python3`, which is the name present on Linux and macOS.
- The Interview step names `.agents/skills/` as the project location, not one host's folder.
- Removed `metadata.owner` and the "Maintaining this skill" section from SKILL.md; steps 6 and 9 now point at the learning-entry and redirect templates.
- Not re-run: task and trigger evals. The description is unchanged.

## 1.0.1 (2026-11-01)
- Description: add "SKILL.md" / "capturing a workflow as a reusable skill" triggers (lost 2/3 runs to built-in create-skill); shorten boundary clause.
- Eval 4: add enforcement expectation (was non-discriminating).
- Lint: skip --help check for test_*/selftest scripts.
- Iteration-1 results: task evals with skill 11/11 vs without 7/11; trigger 18/18 x3 after fix (was 17/18).

## 1.0.0 (2026-10-30)
- Initial version: 10-step workflow, generated phase references, lint/scaffold/trigger-score/sync scripts, self-evals.
