---
name: Report candidate gate labels
description: Candidate gate labels must come from the hard fixture gate, not inferred from package/smoke metric keys.
---

# Candidate gate labels on the report site

`report._candidates_html()` must derive each candidate's gate label from the **hard
fixture gate** (`pass{N}_fixture_gate.json` eligible/blocked lists, loaded in
`gather()` and matched via `_fixture_gate_status_for()`), not from
`metrics.package_ok`/`smoke_ok`.

**Why:** Newer pass run dirs do not write `package_ok`/`smoke_ok` into their
`metrics.json`. Labeling `"ok" if package_ok and smoke_ok else "GATE-FAIL"` then
false-fails every such candidate. Gate status is: `eligible→ok`, `blocked→GATE-FAIL`,
else fall back to package/smoke metrics if present, else `"not evaluated"` (muted) —
never label a not-yet-evaluated candidate as a failure.

**How to apply:** When adding a new pass, load its fixture-gate JSON in `gather()` and
include its key in `_fixture_gate_status_for()` (checked before older passes). Gate ids
are run-dir-prefixed (`<ts>_<idx>_<branch_id>`); match `cid == branch_id` or
`cid.endswith("_"+branch_id)` to keep a delimiter boundary.
