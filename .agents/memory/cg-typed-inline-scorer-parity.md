---
name: cg_typed inline-scorer parity pattern
description: How to share owned policy logic between the repo and a cg_typed candidate tarball that cannot import src/.
---

# cg_typed inline-scorer parity pattern

A `cg_typed` candidate tarball ships `main.py` + `deck.csv` + the `cg/` SDK only; its
`main.py` **cannot import `src/`** (the repo package is not in the tarball). So any
owned policy logic you want to (a) unit-test in the repo AND (b) run inside the
candidate must live in TWO places that are kept provably identical.

**The rule:** keep ONE source of truth as a pure repo module (e.g.
`src/ptcg_activegraph/analysis/turn_scorer.py`) plus a JSON profile under
`data/experiments/`. The candidate generator then **inlines** a byte-identical copy
of that module's "inline region" + embedded profile constants into the candidate
`main.py`. Enforce identity with TWO checks recorded in the build artifact:
- `inline_region_byte_identical` — the inlined text equals `turn_scorer.inline_region_source()` byte-for-byte.
- `parity.behavioral_parity_ok` — repo `score_option`/`choose_indices` vs the inlined
  `_score_option`/`_choose_indices` agree on fixtures (0 mismatches).

**Why:** without the parity gate the two copies silently drift, and the thing you
tested in-repo is not the thing that runs in the tarball. The pure module also lets
the scorer be a never-raise unit (pure feature extraction → weighted family score →
legal index choice) testable without any game/SDK/native `libcg.so`.

**How to apply:**
- Expose `inline_region_source()` and `baseline_profile()`/`DEFAULT_PROFILE` from the
  pure module so the generator and tests both read the same text.
- The pure scorer must never import storage/eventstore/prod/reference code and must
  never raise on garbage input (None/ints/strings/bad dicts) — return a finite float.
- Keep an explicit `unsupported_scorer_claims()` guard: the scorer ranks legal option
  FAMILIES by calibrated weight; it makes NO exact-damage/lethal/missed-KO/Boss-gust/
  spread/best-action claims. Numeric `attackId` only.
- Calibrate the weights OFFLINE (e.g. against the Pass-46E Search oracle on ACTIVE-seat
  replay frames). The live hot path runs only the cheap scorer — NO online Search.
  Record `no_online_search=true` in both the profile and the build artifact.
- Use a robust MEDIAN fit, not mean: fabricated-hidden-zone oracle labels produce
  large outliers that wreck a mean. In-sample lift (median oracle-score improvement,
  top-1 agreement) is a FIT statistic, never a win-rate/generalization claim — prove
  strength only in a separate live H2H panel.
