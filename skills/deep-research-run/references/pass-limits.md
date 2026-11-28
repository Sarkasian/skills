# Item limits and failed passes

Read this when the brief or the user limits the time of the whole item, and when a deep-research pass times out, is cut off, returns nothing or returns an error. It completes the "Time and count" rule of SKILL.md and applies to every engine.

## A limit on the whole item

An item limit covers everything you do: your searches, the engine check, the passes, the waits and step 4.

- **The share.** Passes and the waits before them may use at most two thirds of the item limit, and never more than is left of it. The rest is for your searches and step 4. Time your searches took before the first pass does not reduce the share, as long as that much of the limit is still left.
- **One pass.** The limit for one pass does not change: the limit the brief or the user gives for a pass, otherwise 15 minutes.
- **Before each pass or wait.** Start it only if the time you expect it to take fits in what is left of the share.

Example: 30 minutes for the item gives a share of 20. A 5-minute pass leaves 15, so a second pass of up to 15 minutes fits. If your searches had already taken 14 minutes, 16 are left of the limit, so 16 is all the passes may use.

## A pass that fails

Do these in order.

1. Quote the error under `## Failures`. Do not repeat the same call.
2. If the engine can hand over a finished result later (by an id or a status tool): wait as long as the failed call had run, then ask for the result once. Asking is not a pass.
3. If the engine cannot hand a result over, or asking gave nothing: retry once, smaller, with the quickest mode and a narrower question. The retry is a pass, so one of the two passes must be left.
4. With an item limit, the wait and the retry must fit in what is left of the share. Shorten the wait in 2 to what fits. If the retry in 3 does not fit, do not start it.

With no item limit only the count stops you: a first pass cut off at its 15 minutes may be followed by a retry.

When the retry has failed too, or cannot be started, no further pass can be started: the stop rule of SKILL.md applies.
