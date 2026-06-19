# Pass 20 — Candidate preflight (Part C)

> LOCAL ONLY for the verification itself. The internal league is **not** a Kaggle
> leaderboard; this preflight verifies the artifact, it does not predict the Kaggle score.

- **candidate_id:** `league_water_core_reference`
- **tarball:** `data/submissions/candidates_pass17/league_water_core_reference.tar.gz`
- **exists:** yes
- **members:** exactly `main.py` + `deck.csv` (no nested paths, no extra files)
- **is root repackaged:** no (distinct candidate from the Pass-17 Water reference manifest)

## Deck
- **rows:** 60 (all integer rows)
- **unique card ids:** 11
- **non-energy counts legal:** yes (max non-energy copy count = 4; basic energy `3` ×29 is legal)
- **card ids all in card DB:** yes (`data/cards/EN_Card_Data.csv`)
- **card ids match Pass-17 manifest:** yes (`playbooks/pass17_water_core_reference.yaml`)

| id | name | count |
|---|---|---|
| 3 | Basic {W} Energy | 29 |
| 721 | Kyogre | 4 |
| 722 | Snover | 4 |
| 723 | Mega Abomasnow ex | 4 |
| 1092 | Secret Box | 1 |
| 1121 | Ultra Ball | 4 |
| 1145 | Mega Signal | 2 |
| 1163 | Powerglass | 2 |
| 1219 | Team Rocket's Petrel | 4 |
| 1227 | Lillie's Determination | 4 |
| 1262 | Surfing Beach | 2 |

## Validators
- tarball validator: **PASS** (rc=0) — 60-card deck on select=None/current=None
- entrypoint validator: **PASS** (rc=0) — last top-level callable `core_pilot_agent` returns 60 on deck-selection and legal indices on gameplay

## Root safety
- `package_submission.py --verify-only`: **PASS**
- root `main.py` unchanged vs v1 baseline: **yes**
- root `deck.csv` unchanged vs v1 baseline: **yes**

## Verdict
**preflight_passed: true** — no blockers.
