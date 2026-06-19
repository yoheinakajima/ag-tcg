# Pass 20 — Live smoke + core-competency gate (Part E)

> LOCAL ONLY. Real `kaggle_environments.make("cabt")` smoke + core-competency gate.
> Does **not** predict the Kaggle leaderboard score.

- **candidate_id:** `league_water_core_reference`
- **tarball:** `data/submissions/candidates_pass17/league_water_core_reference.tar.gz`

## Core-competency gate
- verdict: **PASS** (rc=0)
- total 14 | pass 13 | fail 0 | advisory 1 | **hard failures 0**
- reports: `data/reports/pass14_core_gate.{json,md}`

## Live cabt smoke (self-play, both seats)
- status: **PASS**
- steps: 176
- bad statuses: none
- final statuses: `["DONE", "DONE"]`
- deck size: 60
- The candidate runs as both seat 0 and seat 1 in a real cabt env — no INVALID/ERROR/TIMEOUT.
- artifact: `data/experiments/pass20_smoke/candidate_smoke_league_water_core_reference.json`

## vs-anchor note
`league_water_core_reference` **is** the clean Water reference, so the both-seats self-play already
exercises the Water-reference matchup. No separate distinct local anchor is available without a deck
change (disallowed by guardrails).

## Verdict
**all_gates_passed: true** — no blockers.
