# Decomposition

Build the plan as a pyramid. The governing question is at the top. Each node splits into children that do not overlap and that together answer it.

## Split

1. Split the governing question into 2 to 7 children. Two children must never produce the same deliverable, and together they must cover every part of the question. With more than 7, add a grouping level.
2. Test each child:
   - **Atomic → leaf.** It has one deliverable and a checklist that a reader can check from the result alone. It has one return format. One executor can do it without asking anything.
   - **Splittable now → group.** Split it again from step 1.
   - **Cannot be split until something is known → deferred group.** Add the group with no children. Then add one discovery leaf whose goal is to find that out, **beside** the group (same `--parent`, never inside it), with `--discovers <group id>`. When the discovery leaf is done, `next` lists the group in `expand`.
3. For each fact a leaf needs, look it up first: the workspace files, the installed skills, a web search. Write a fact you find into the leaf's goal or checklist and do not ask it. A fact you cannot find becomes a question:
   - *scope*: what the user wants, such as audience, depth, criteria or thresholds;
   - *user-only*: what only the user knows, such as a name, a budget, an owner or a date.

   Ask with `ad ask --task <T> --type scope|user_only --text "<question>" --default "<your proposed answer>"`. Every question needs a default you would act on.
4. In the first decomposition only: for every real choice between options that has no settled criteria, add a scope question asking for the criteria.

## Add

Make one `ad add` call per node, parents before children.

- `--parent root|<id> --title "<unique title>" --kind group|leaf`
- A leaf also takes:
  - `--goal "<the one deliverable>"`;
  - `--check "<entry>"`, once per checklist entry a reader must judge, each one checkable from the result file alone;
  - `--check-cmd "<command>"` for an entry a command can check: exit 0 means it holds. The script runs it in the item's working tree, so use paths relative to that tree, with no `cd` and no absolute workspace path. Never read `.atomic-decompose/` or `.git/`, which hold the command's own text, for example `! grep -rw calc_total pkg tests README.md`. A leaf needs at least one `--check` or `--check-cmd`;
  - `--returns "<format, for example a Markdown table with columns ...>"`.
- `--needs Q1,Q2`: the questions whose answers the item uses. The script adds the needs of its dependencies itself.
- `--depends <ids>`: the items whose results this item builds on. Naming a group means all of its leaves.
- `--writes`: the item changes workspace files (code, config, docs). git records its change, so it returns no diff (delegation.md, *Workspace changes*). Leave it off an item that only writes its result file.
- `--small`: a short item, such as a lookup, one small file or one short section. Small siblings run together in one brief.
- `--skill <absolute path of SKILL.md>`: an installed skill whose description fits the item. Use the path your host lists for that skill (delegation.md, *Skill paths*).
- `--chain-after <id>`: run this leaf as the next step after leaf `<id>`, done by the same executor. Use it when the leaf depends on `<id>`, both read and change largely the same files, no result between them could change the plan, and no approval sits between them. On `chain_invalid`, add the leaf again without it.

Two leaves that will change the same file never run side by side: order them with `--depends`, and chain them with `--chain-after` when the chain stays within `max_chain`. A command that checks the task's end condition goes only on the writes leaf whose completion makes it true, depending on the leaves it covers. Never put it on a separate check leaf, since `finish` reruns only the commands of done writes items.

Titles must be unique, and a dropped item's title still counts, so a replacement takes a new title.

## Validate

Run `ad validate --task <T>` until it prints `"ok": true`.

| Problem | Repair |
| --- | --- |
| `childless_group` | Add the group's children, or drop the group. |
| `duplicate_title` | Retitle by dropping the item and re-adding it under a new title. |
| `cycle` | Remove the dependency loop. This includes a leaf that depends on its own ancestor group. |
| `dangling_dependency` | `ad drop <item> --cause <the dropped item it named>`, then re-add the item under a new title with `--depends` naming the items that now deliver what the dropped one did, or none. |
| `open_question` | Clears in the question round. |

## Re-entry

Come back here when one of the following happens, then `add` and `validate` again. When the re-plan added a writes item, show the updated plan and log it (SKILL.md step 3, *The plan the user saw*):

- **A discovery leaf is done.** Its group appears in `next`'s `expand`. Add the group's children from *Split*. If the discovery shows there is nothing to add, `ad drop <group>` and name the group in the result.
- **A result contradicts the plan.** Drop the pending items of the nodes it contradicts and re-expand those nodes.
- **A scope answer arrives after the question round.** Re-expand every node that is not done, from the governing question.
- **An answer change resets a failed item.** The items whose `item_dropped` cause is that item, read from `<T>/record.jsonl`, go back in under new titles. If the reset item is a discovery leaf whose group was dropped, `ad drop <that leaf>`, then add a new deferred group and discovery leaf.
- **An item fails for good.** `ad drop <id> --cause <failed id>` every pending item whose `depends_on` chain reaches it. Name them all, with the failed item, in the result.
