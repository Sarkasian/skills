Task t-fts, items 1: you do all of them, alone, in this order. Work in . (cd there first; change files only there).
Request: Which database should our notes app use for full-text search?
One item at a time: do its goal and run its `done` command before you start the next item, because `done` commits every change in the item's files. `done` runs the checks first; on a failure it prints why: fix it and run `done` again, at most 3 times, then go on. Only `done` commits: never run git commit, reset, clean or stash, or change the task folder.
Need a fact only the user knows: echo "block <id> --question '<q>'" >> blocks.log, then go on.
A step outside the goal (other files, deleting, contacting anyone): echo "block <id> --approval '<step>'" >> blocks.log, then go on.
Do not ask the user anything. Reply with one line per item saying what you did.

ITEM 1: Compare built-in full-text search in SQLite, PostgreSQL and MySQL   [Skill: deep-research-run, load it first]
Result: write it to results/1.md; change no workspace file
Goal: Compare the full-text search that ships with SQLite (FTS5), PostgreSQL (tsvector and tsquery) and MySQL (InnoDB FULLTEXT). For each: whether it is built in or needs an extension to be enabled, how results are ranked, and which tokenizers or language configurations it offers.
Judged by: for each of the three databases, says whether full-text search is built in or must be enabled; names the ranking function or method of each; names the tokenizer or language options of each, from that database's own documentation
Done: echo "done 1" >> done.log
