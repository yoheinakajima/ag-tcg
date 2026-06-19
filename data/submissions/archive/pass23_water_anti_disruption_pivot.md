# Pass 23 — Pre-upload Archive: Water Anti-Disruption Pivot Probe

- archived: 2026-06-19T07:21:49.631268Z
- source tarball: `data/submissions/candidates_pass22/league_water_anti_disruption_pivot_v1.tar.gz`
- archived copy: `data/submissions/archive/pass23_water_anti_disruption_pivot_probe.tar.gz`
- candidate_id: `league_water_anti_disruption_pivot_v1`
- tarball sha256: `b67c1f33b3b0c3a54fa30e32f303e0529d627427d205028682e7e90747ffee42`
- members: ['deck.csv', 'main.py']
- deck rows: 60 (unique 11)
- runtime_contexts: [0, 7, 8] (ctx0 emergency backup bench, ctx7 search pivot, ctx8 discard preservation)

## Validation results
- candidate preflight (Part C): ALL PASS (11/11)
- tarball validator: PASS (rc=0) — 60-card deck on key-absent deck-selection obs
- entrypoint validator: PASS (rc=0) — last callable core_pilot_agent, legal gameplay indices
- default core-competency gate: 13 pass / 1 advisory / 0 hard-fail -> PASS
- pass22 board-safety gate: 9/9 PASS

## Smoke results
- live cabt self-play: DONE — one full game, INVALID 0 / ERROR 0 / TIMEOUT 0, finite rewards
- candidate-vs-reference: covered by Pass 22 decision replay (75 windows, 5 legal corrections)

## Planned upload message (exact)
`water_anti_disruption_pivot_v1: replay-derived board-safety probe; prevents empty-bench/backup-basic failures; validators+smoke PASS; calibration only`

## Guardrails
- no root mutation: root main.py / deck.csv byte-identical to data/baselines/v1_kaggle_349_8 (cmp clean)
- no promotion claim: this is a human-approved single live CALIBRATION probe, not a promotion
- no GitHub push; no second upload this pass; tarball top-level main.py + deck.csv only
