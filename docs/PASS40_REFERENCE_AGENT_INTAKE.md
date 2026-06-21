# Pass 40 — Public Reference Agent Intake

_Status lane: `external_reference` (benchmark opponents only). Internal benchmark scores are NOT Kaggle scores and NOT a strength claim._

## What this is

Pass 40 intakes public Kaggle *rule-based sample* agents (the host's kiyotah samples + one optional public competitor notebook) as **benchmark opponents** for the standing ActiveGraph tournament engine. They let us calibrate our own gameplay against known public typed (cg-SDK) agents in the *local* cabt harness. They are never our candidates.

## Hard guardrails

- NO Kaggle upload / submit / auto-submit; every Pass 40 event carries `no_upload=true`.
- NO root `main.py` / `deck.csv` mutation; NO candidate tarball mutation or deletion; NO GitHub push; NO candidate generation.
- References are NEVER in the submission queue, promotion, mutation lineage, lifecycle, family-champion set, active-cap, or any "our best" ranking — proven by the zero-leakage checks (Part H) and the Pass 40 test suite.
- The cg SDK / `libcg.so` / `*.csv` / PDFs / images stay gitignored; only manifests + hashes are committed.

## Reference agents

| agent_id | label | archetype | source | optional |
|---|---|---|---|---|
| `public_ref_kiyotah_dragapult` | public_reference_dragapult | Dragapult ex | host sample | no |
| `public_ref_kiyotah_iono` | public_reference_iono | Iono's deck | host sample | no |
| `public_ref_kiyotah_mega_abomasnow` | public_reference_mega_abomasnow | Mega Abomasnow ex | host sample | no |
| `public_ref_kiyotah_mega_lucario` | public_reference_mega_lucario | Mega Lucario ex | host sample | no |
| `public_ref_ryotasueyoshi_alakazam` | public_reference_alakazam | Alakazam (rule-based) | public competitor | yes |

## Lanes

- **stdlib lane** — our own candidates (pure-stdlib `main.py`); unchanged and intact (the cg_typed validator does NOT weaken it).
- **cg_typed lane** — reference agents import the bundled `cg` SDK; validated separately (see `docs/CG_TYPED_LANE_VALIDATOR.md`).
- **benchmark lane** — references registered on a SEPARATE benchmark ledger (`data/tournament/benchmark/benchmark_events.jsonl`) via `PublicReferenceAgentRegistered`; benchmark games use `PublicBenchmark*` events that the normal fold / scheduler / lifecycle never read.

## How to run (local only)

```bash
python3 scripts/build_pass40_tournament_benchmark_integration.py  # Part H proof
python3 scripts/build_pass40_benchmark_tick.py                     # Part I games
python3 scripts/build_pass40_public_reference_gap_report.py        # Part J gap
```

## Current benchmark snapshot

- {'games': 8, 'our_win': 1, 'reference_win': 7, 'draw': 0, 'invalid': 0}  (our decisive win rate: 0.125)
- Across 8 controlled local games (0 invalid = the lane runs cleanly end-to-end), our candidates won 1 and the public typed references won 7 (our decisive win rate 0.125).
- This is a SMALL sample and benchmark-only: it is directional feasibility, NOT a strength claim and NOT predictive of any Kaggle leaderboard score.
- Direction: the public cg-SDK (typed) sample agents currently out-perform our sampled stdlib candidates in head-to-head local cabt play. The cg_typed lane is validated and importable, so typed gameplay is a feasible future exploration seam — but no candidate generation is performed in this pass.
