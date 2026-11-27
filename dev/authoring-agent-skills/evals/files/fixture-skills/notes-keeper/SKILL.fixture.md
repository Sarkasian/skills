---
name: notes-keeper
description: "Files meeting notes into the team notes folder. Use when asked to save, file or tidy meeting notes. Not for writing the notes themselves."
---
# Notes keeper

Copy this checklist and tick it off:
- [ ] 1. Read the note. Its first line must hold the meeting date as YYYY-MM-DD.
- [ ] 2. Name the file `<date>-<topic>.md`, topic in lowercase with hyphens.
- [ ] 3. Put it in `notes/<year>/`. Create the year folder if it is missing.
- [ ] 4. Add one line for it to `notes/INDEX.md`, newest first.
- [ ] 5. Report the path you wrote.

## Never
- Never delete a note. Move it to `notes/archive/` instead.
- Never overwrite a note that exists. Add `-2`, `-3` and so on to the name.
- Never file a note with no date in its first line. Stop and ask for the date.

## Size
`python3 scripts/check_size.py` must exit 0 after every edit to this file.
