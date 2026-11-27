# Report

When the action is `report`, write:

1. A first sentence answering the plan's `question`.
2. The supporting points, grouped by requirement.
3. Each decision: the chosen option, and each rejected option with why it lost.
4. Each skill used, with its items.
5. Last: failed items and why, review gaps, `changed_answers` and the items they affect, `untracked_left`, the cost, and each `unconfirmed_defaults` entry for the user to confirm.

When the user accepts, run `ad mark --mark accepted --task <T>`. For rework, run `ad mark --mark reworked --reason "<reason>" --task <T>` and do its `next`.
