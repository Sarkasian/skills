# Agents

Rules for how agents should interact with this repository.

## Before pushing to `main`

**Always run the CI checks locally first.** If they fail locally, they fail on push.

```bash
# Selftests
for t in dev/*/selftest.py; do python3 "$t"; done

# Lint every skill
for s in skills/*/; do
  name=$(basename "$s")
  python3 skills/authoring-agent-skills/scripts/lint_skill.py "$s" --portable \
    --evals-dir "dev/$name/evals"
done
```

The `check.yml` workflow runs exactly these commands. If they pass here, they pass on push.

## Pushing code

**All code must be pushed on a branch in a PR**, unless the user explicitly says otherwise. Never push directly to `main` — the CI only runs on PRs and pushes, so pushing to `main` from a branch lets the CI catch regressions before they merge.

```bash
# Correct: branch → PR
git checkout -b my-change
# ... make changes ...
git push origin my-change
# Open PR, wait for CI to pass, merge

# Wrong: direct push
git push origin main
```

Direct pushes bypass the PR review process and can land CI failures on `main` if checks aren't run locally first.
