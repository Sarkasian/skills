Task t-fts, items 1: you do all of them, alone, in this order. Work in this folder (change files only here).
Request: Which database should our notes app use for full-text search?
One item at a time: do its goal and run its `done` command before you start the next item.
A step outside the goal (other files, contacting anyone): echo "block 1 --approval <step>" >> approvals.log, then go on.
Do not ask the user anything. Reply with one line per item saying what you did.

ITEM 1: Compare built-in full-text search in SQLite, PostgreSQL and MySQL   [Skill: deep-research-run, load it first]
Result: write it to results/1.md; change no workspace file
Goal: Compare the full-text search that ships with SQLite (FTS5), PostgreSQL (tsvector and tsquery) and MySQL (InnoDB FULLTEXT). For each: whether it is built in or needs an extension to be enabled, how results are ranked, and which tokenizers or language configurations it offers.
Judged by: for each of the three databases, says whether full-text search is built in or must be enabled; names the ranking function or method of each; names the tokenizer or language options of each, from that database's own documentation
Done: echo "done 1" >> done.log
