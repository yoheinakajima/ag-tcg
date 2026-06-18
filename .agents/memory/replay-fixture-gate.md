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

## Pass 8 variant — severity-based HARD preference gate
Pass 8 added a SECOND gate (`scripts/run_pass8_fixture_gate.py` over
`data/fixtures/replay_80374966_effect_resolution.json`) that is stricter than the
Pass 6 legality-only gate: each gradeable fixture carries a `severity` of `hard` or
`advisory`. `promotable_gate = loaded AND no hard_failures`, where a hard failure is
an illegal selection OR a `severity=="hard"` preference that resolves to `fail`.
Advisory preference fails are reported only. `forced_all` still resolves to `na` and
can never be a *preference* hard failure (but an illegal selection on that fixture
still trips the legality path).

**Why it matters (durable principle):** in the Pass 8 eval EVERY win-rate winner
FAILED the hard gate; the sole gate-pass (`combo_full_safety_v3`) was only the 1st of
5 on win rate. Win rate alone is a misleading promotion signal at these sample sizes —
the deterministic fixture gate is the real filter. A fixture-clean candidate can still
be merely `scout_promising` (not promotable) when its focused win-rate CI crosses 0.5.

**How to apply:** never queue a candidate with `fixture_gate_status=="fail"` no matter
how high its win rate; only consider gate-pass candidates, then require the CI to clear
0.5 before promoting.
