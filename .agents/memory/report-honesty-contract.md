---
name: report honesty contract
description: Honesty rules the experiment report renderers must obey so they never fabricate conclusions.
---

# Report honesty contract

The experiment report renderers (`experiments/report.py`, both `_*_html` and `_*_md`)
must never state a conclusion that is not backed by a loaded artifact.

**Rule:** any narrative sentence that summarizes data (e.g. "all chaos seams are
blocked") must be DERIVED from the loaded artifact at render time, not hardcoded.
When the artifact is missing/empty, degrade to an explicit "uncertain" / "not loaded"
statement and skip the findings tables entirely.

**Why:** a hardcoded summary line ("All chaos seams remain blocked…") still printed
even when no contract was loaded — a fabricated conclusion. A reviewer flagged it.
The same trap applies to any section whose heading implies findings (the Pass-5
section title literally contains "deck-out", so substring tests for fabrication must
check for *findings* like "Apparent loss reason"/"Strongest failure tag", not the
heading word).

**How to apply:** put the summary logic in a small helper that inspects the data
(e.g. `_chaos_summary(chaos)` returns "uncertain" when `seams` is empty, "All N
blocked" only when every seam is blocked, "M of N … remainder uncertain" otherwise).
Cover the empty-artifact and mixed cases with unit tests so the fallback can't
silently regress.
