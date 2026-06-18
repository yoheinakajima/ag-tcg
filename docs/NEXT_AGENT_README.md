# Next Agent — Start Here

You are continuing the Pokémon TCG AI Battle Challenge ActiveGraph lab. Read this
first, then read `docs/ACTIVEGRAPH_LAB_OPERATING_MANUAL.md` before doing anything.

## The five rules you must not break

1. **Read `docs/ACTIVEGRAPH_LAB_OPERATING_MANUAL.md` first.** It has the golden
   invariants, the pipeline, and the lessons already paid for.
2. **Do not upload to Kaggle by default.** No upload or submit unless a human
   explicitly approves it. Complete the upload checklist in the manual (§8) first.
3. **Do not mutate root files.** Root `main.py` and `deck.csv` are immutable
   (match `data/baselines/v1_kaggle_349_8/`). Verify with `cmp`.
4. **Validate tarballs.** Every candidate must pass
   `scripts/validate_candidate_tarball.py` (key-absent / select-null / empty-dict /
   Struct-like obs, exactly 60 ids, exactly top-level `main.py` + `deck.csv`).
   No failed-validator candidate enters queue/eval/upload.
5. **No raw data commits.** Raw replays and official card data
   (`data/cards/*.csv`, `data/kaggle_ref/*.csv`) stay gitignored. Never invent
   card IDs. Never commit credentials/secrets.

## Things that will bite you

- **Active control is dynamic.** Recompute it from
  `data/kaggle_uploads/live_score_registry.json`; never hardcode a score.
- **The kaggle CLI is often absent** (`kaggle: command not found`). When you
  cannot refresh scores, reuse the last-known-good snapshot and *say so*.
  `build_live_score_registry.py` defaults to a **stale** CSV — pass
  `--csv data/kaggle_uploads/status_before_pass11b.csv`.
- **cabt runs via `kaggle_environments.make("cabt")`** even if `import cabt`
  fails. Don't conclude cabt is missing from an import error.
- **Card id→name comes from `data/cards/EN_Card_Data.csv`** (authoritative), not
  from `archetypes.yaml` names (which had ids 678/756 swapped).
- **Long evals need a Replit workflow.** Background shells die between tool calls.

## What the next research task is

The `unknown_ex_tempo` bucket has been decomposed (Pass 13) into four
evidence-grounded subfamilies — `mega_lucario_ex_tempo`,
`mega_kangaskhan_energy_stack`, `dragapult_ex`, `lightning_bellibolt` — with a
refined meta pool at `experiments/pass13_refined_meta_pool.yaml`.

**Next:** run a proper analysis-only eval of the existing active control and
existing candidates against these refined surrogate decks (5 games/seat,
seat-swapped, no new candidates, no upload), then decide whether any subfamily
warrants a *targeted* candidate built only from confirmed card IDs. The chaos
lane stays closed until a payoff card + measurable trigger is confirmed (see
`docs/CHAOS_PLAYBOOK_LANE.md`).
