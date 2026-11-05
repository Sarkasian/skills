# Learnings

- Propose: add one file per lesson in `proposed/` using the learning-entry template. Only from a real signal: eval failure, validator error, or human correction.
- Accept: a human merges it into `references/` or SKILL.md Gotchas, adds an eval case, and appends one line to `accepted.jsonl`.
- Never rewrite this folder or the playbook wholesale; append and edit in place.
- Prune entries whose `harmful` count exceeds `helpful`, or whose eval no longer discriminates.
