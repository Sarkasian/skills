---
name: csv-profile
description: Profiles CSV files, reporting per column the inferred type, null count and percentage, distinct count and duplicate values of id-like columns. Use when asked to profile, inspect or check the data quality of a CSV file.
---

# CSV profile

For each CSV file:

1. Read the header and every row with Python's `csv` module.
2. For each column report: inferred type (int, float, date, text), null count and percentage (empty string counts as null), distinct count.
3. For each column whose name ends in `_id` or equals `id`, list every duplicated value with its row numbers.
4. Write the profile as a Markdown table per file, then a list of problems: any duplicated id value, and any column over 1% null.

Name this skill (`csv-profile`) in what you return.
