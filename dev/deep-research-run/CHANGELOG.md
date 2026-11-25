# Changelog

SemVer. Major: rename, trigger-scope change, removed script/flag, config schema break. Minor: new optional config/reference, deprecation. Patch: wording fixes that pass evals.

## 0.1.0 (2026-11-26)

Not tagged. First version: the research method for one question on the local-deep-research (LDR) engine. It checks the engine's configuration, picks the cheapest tool, runs a breadth pass and at most one depth pass, tags each claim with how far it was verified, and writes a result file with open threads.

The evals in `evals/` have not been run. The description was rewritten to fit the 400-character listing budget, so the trigger evals are due before a release.
