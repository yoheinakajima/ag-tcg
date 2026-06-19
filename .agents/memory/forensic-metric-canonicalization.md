---
name: Forensic metric canonicalization
description: Why derived gameplay metrics must flow from the forensics analysis layer, not raw per-deck diagnostics, and how to guard it.
---

When a Pass-N forensic pipeline computes a representative metric (e.g. first-attack
timing), the **forensics analysis layer is canonical**. Every downstream builder
(matrix, priority, reports/canvas/site, roadmap, fixtures) must source that metric
from the forensics output — never from the raw per-deck diagnostic.

**Why:** raw per-deck diagnostics can surface single-game artifacts. A global-min /
single-game first-attack value (e.g. step 98 from one stalled `charizard__vs__water`
game) produced a false "uniformly slow Mega line" narrative; the honest metric is the
**median of per-(run,game) first-attack steps** (charizard median 6 / min 4, with a
long tail of stalled games). Use median + min + an explicit `*_semantics` string so
the value is self-describing.

**How to apply:**
- Compute the representative metric once in forensics; emit `<metric>`,
  `<metric>_min`, and `<metric>_semantics`.
- In every downstream builder, pull the metric from the forensics evidence dict, not
  from `diagnostic.per_deck`. Avoid hardcoding the number into string literals — read it.
- Add a cross-artifact consistency regression test that (a) asserts forensics carries
  the min + semantics fields, (b) asserts each downstream artifact references the
  canonical value, and (c) blocks the stale outlier in ALL phrasing variants. Grep for
  variant spellings (`step 98`, `step ~98`, bare `~98`) — an exact-token test misses
  `~`-prefixed copies and lets stale values survive a green suite.
