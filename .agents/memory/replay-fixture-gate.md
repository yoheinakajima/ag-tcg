---
name: Replay fixture gate (Pass 6 Stage 0)
description: How the pre-cabt decision-fixture gate grades candidates; why v2 fails some checks by design
---

The fixture gate (`scripts/test_candidate_on_fixtures.py` over `data/replay_fixtures/`)
grades a candidate `main.py` on two INDEPENDENT axes per frozen decision prompt:

- **legality (HARD gate)**: action is a list of unique, in-range indices respecting
  minCount/maxCount and the agent must not raise. `legality_gate` is True only if every
  fixture is legal and nothing crashed. Every candidate (incl. v2) must pass this.
- **preference (ADVISORY)**: per-fixture strategy check — `decline` / `avoid_cards` /
  `prefer_cards` / `forced_all`. `forced_all` is always `na` (no avoidable choice).

**Why:** v2 (active control) intentionally FAILS 3 advisory preferences — mega-no-snover
search (step17), discarding Mega as Ultra Ball cost (step28), over-searching near deckout
(step112). Those failures are the *targets* a v3 policy (Part F) must flip to pass. So the
gate records baseline weaknesses; it does not require preferences to pass.

**How to apply:** Stage 0 uses `legality_gate` as a hard pre-cabt reject; preference
pass/fail is reported for ranking/report, not used to reject. A v3 candidate is "good" when
it keeps legality_gate=True AND converts the v2 preference fails to pass.

Nuance worth remembering: step11 Secret Box has minCount==maxCount==n_options==3, so the
only legal selection is ALL options — a setup piece (Snover 722) cannot be spared. This is
a *forced* discard, recorded as `forced_all`/`na`, NOT a policy failure.
