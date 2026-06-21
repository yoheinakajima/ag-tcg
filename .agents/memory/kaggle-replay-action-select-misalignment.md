---
name: Kaggle replay action/select misalignment
description: Why an empty per-seat action at a minCount>0 select frame is NOT proof of an illegal play in cabt/kaggle replays.
---

# Kaggle replay action↔select misalignment (legality honesty)

In the only local full-frame Kaggle replay, the per-seat `action` field does **not**
reliably align with the `select` shown in the *same* frame. Measured in that replay:
many ACTIVE frames carry a `select` with `minCount>=1` yet an **empty** `action`
(dozens of them), while `INACTIVE` seats sometimes carry non-empty actions. When an
action *is* present it is in-range the large majority of the time, so the alignment
holds for present actions but breaks for the empty ones.

**Rule:** a turn-planning / legality extractor must treat an empty selection with
`minCount>0` as **not checkable** — return tri-state legality `None` with an explicit
note (e.g. "selection absent with minCount>0: legality not checkable"), never a
fabricated `False`. An empty selection with `minCount==0` is a legitimate legal pass
(`True`). Only flag `False` for a *present* selection whose indices are out of
`[0,n_options)` or whose count is outside `[minCount,maxCount]`.

**Why:** a literal "empty + minCount>0 = illegal" rule (a plausible architect
suggestion) would fabricate dozens of false illegal-play flags in a single real game —
an honesty violation. The agent would have lost instantly if those were real illegal
plays; instead they are a trace-alignment artifact.

**How to apply:** any code that maps a replay seat's `action` onto the `select`
presented that frame (legality checks, selected-family/first-attack derivation) must
guard the empty-action case as unverifiable, and tests must assert the `None`+note
behavior rather than asserting illegality.
