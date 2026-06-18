# Meta replay summary (Pass 10)

- raw replays analyzed: **1**
- missing external replays: **metal_ex_zacian_ramp, water_kyogre_abomasnow_maxbelt**

## Episode 80374966
- source: `data/meta_replays/raw/80374966_self_mirror.json`
- agents: ['Yohei Nakajima', 'Yohei Nakajima']
- self-mirror: **True**
- steps: 136, rewards: [-1, 1], winner seat: 1
  - **seat 0** (Yohei Nakajima): won=False, first_attack_turn=3, evolved_mega_abomasnow=False, stuck_on_basic_snover=True, max_bench=4, decked_out=True (min_deck=0)
  - **seat 1** (Yohei Nakajima): won=True, first_attack_turn=3, evolved_mega_abomasnow=False, stuck_on_basic_snover=True, max_bench=2, decked_out=False (min_deck=7)

## Tempo failure signals (from real replay)
- episode 80374966 seat 0: stuck on basic Snover (never evolved Mega Abomasnow ex)
- episode 80374966 seat 0: decked out (deckCount reached 0) — over-thinning / passive long game
- episode 80374966 seat 1: stuck on basic Snover (never evolved Mega Abomasnow ex)

## Archetypes
- **water_kyogre_abomasnow_mirror_passive** — confirmed_from_replay (card_ids: confirmed)
- **metal_ex_zacian_ramp** — blocked_missing_replay (card_ids: unknown)
- **water_kyogre_abomasnow_maxbelt** — blocked_missing_replay (card_ids: unknown)
