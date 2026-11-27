# Report

When the action is `report`, the output is the summary: `ad finish --task <T>` prints it again. Write:

1. A first sentence answering the plan's `question`.
2. The supporting points, grouped by requirement.
3. Each decision: the chosen option, and each rejected option with why it lost.
4. Each skill used, with its items.
5. Last, each of these that is not empty:
   - failed items and why;
   - review gaps. When `review_state` is `missing`, say that the work was to be reviewed and no review was written, so it is not reviewed;
   - `changed_answers` and the items they affect;
   - `untracked_left`: new files the task left that no commit holds;
   - `outside_patches`: changes an executor made to files of no item. They did not land and are saved in these patch files;
   - `branches_left`: branches that hold an attempt that clashed and was redone. The user may delete them;
   - the cost;
   - each `unconfirmed_defaults` entry, for the user to confirm.

In a git repository, say which branch the commits are on (`start` printed it as `commits`) and that nothing was pushed.

When the user accepts, run `ad mark --mark accepted --task <T>`. For rework, run `ad mark --mark reworked --reason "<reason>" --task <T>` and do its `next`. If the user says neither, run `ad mark --mark unmarked --task <T>`.
