# Replay registry (Pass 11B)

- replays in inbox: **19**
- registered (deduplicated): **19**
- duplicates skipped: **0**
- parse errors: **0**
- known own decks: combo_full_safety_v3_fixed, pass10_candidate_cand_a, pass10_candidate_combo_effect_resolution_v3__secret_box_safety, pass10_candidate_combo_full_safety_v3, pass10_candidate_combo_full_safety_v3_fixed, pass10_candidate_deck_energy_trim_light, pass10_candidate_deck_energy_trim_medium, pass10_candidate_deck_less_draw_more_attack, pass10_candidate_deck_no_secret_box, pass10_candidate_playbook_attack_deadline, pass10_candidate_playbook_bench_safety, pass10_candidate_playbook_fast_evolution, pass10_candidate_playbook_hybrid_tempo, pass10_candidate_playbook_kyogre_tempo, pass10_candidate_policy_pass_avoidant, pass10_candidate_policy_winner, v1_deck_loader_fix, v2_deck_energy_trim_light

| episode | perspective | our_seat | reward | opponent archetype | confidence |
|---|---|---|---|---|---|
| 80374966 | self_mirror | [0, 1] | None | - | - |
| 80503687 | self_mirror | [0, 1] | None | - | - |
| 80503804 | our_loss | 0 | -1 | metal_ex_zacian_ramp | confirmed |
| 80504288 | our_loss | 1 | -1 | water_kyogre_abomasnow_maxbelt | confirmed |
| 80504942 | our_win | 1 | 1 | unknown_ex_tempo | provisional |
| 80505567 | our_loss | 1 | -1 | unknown_ex_tempo | provisional |
| 80506042 | our_loss | 1 | -1 | unknown_ex_tempo | provisional |
| 80515553 | our_win | 1 | 1 | unknown_ex_tempo | provisional |
| 80516161 | our_win | 1 | 1 | unknown_ex_tempo | provisional |
| 80590776 | self_mirror | [0, 1] | None | - | - |
| 80591511 | our_loss | 1 | -1 | unknown | unknown |
| 80592173 | our_win | 0 | 1 | unknown_ex_tempo | provisional |
| 80592831 | our_loss | 0 | -1 | unknown | unknown |
| 80593320 | our_loss | 0 | -1 | unknown | unknown |
| 80594489 | our_loss | 1 | -1 | water_kyogre_abomasnow_maxbelt | confirmed |
| 80595014 | our_loss | 1 | -1 | water_kyogre_abomasnow_maxbelt | confirmed |
| 80622626 | self_mirror | [0, 1] | None | - | - |
| 80622745 | our_win | 1 | 1 | unknown | unknown |
| 80623232 | our_loss | 1 | -1 | unknown_ex_tempo | provisional |

## Per-episode detail
### Episode 80374966 — self_mirror
- file: `80374966_self_mirror.json` (sha256 `a23386d1297a…`)
- agents: ['Yohei Nakajima', 'Yohei Nakajima'], rewards: [-1, 1], steps: 136
  - seat 0 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed
  - seat 1 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed

### Episode 80503687 — self_mirror
- file: `80503687.json` (sha256 `a06fc291d98b…`)
- agents: ['Yohei Nakajima', 'Yohei Nakajima'], rewards: [-1, 1], steps: 79
  - seat 0 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed
  - seat 1 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed

### Episode 80503804 — our_loss
- file: `80503804.json` (sha256 `f41e8d3d31a2…`)
- agents: ['Yohei Nakajima', 'tellurium_rrr'], rewards: [-1, 1], steps: 37
  - seat 0 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed
  - seat 1 (opponent, tellurium_rrr): deck=`opponent_unknown` uniq=12 archetype=metal_ex_zacian_ramp/confirmed

### Episode 80504288 — our_loss
- file: `80504288.json` (sha256 `533a9e934953…`)
- agents: ['AI Agent By TYMU', 'Yohei Nakajima'], rewards: [1, -1], steps: 134
  - seat 0 (opponent, AI Agent By TYMU): deck=`opponent_unknown` uniq=9 archetype=water_kyogre_abomasnow_maxbelt/confirmed
  - seat 1 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed

### Episode 80504942 — our_win
- file: `80504942.json` (sha256 `678b139d5bcf…`)
- agents: ['Ingenio', 'Yohei Nakajima'], rewards: [-1, 1], steps: 202
  - seat 0 (opponent, Ingenio): deck=`opponent_unknown` uniq=16 archetype=unknown_ex_tempo/provisional
  - seat 1 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed

### Episode 80505567 — our_loss
- file: `80505567.json` (sha256 `c63e5fa9a3cf…`)
- agents: ['Zenith08', 'Yohei Nakajima'], rewards: [1, -1], steps: 28
  - seat 0 (opponent, Zenith08): deck=`opponent_unknown` uniq=3 archetype=unknown_ex_tempo/provisional
  - seat 1 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed

### Episode 80506042 — our_loss
- file: `80506042.json` (sha256 `b9bfb7c675a7…`)
- agents: ['rotto', 'Yohei Nakajima'], rewards: [1, -1], steps: 156
  - seat 0 (opponent, rotto): deck=`opponent_unknown` uniq=17 archetype=unknown_ex_tempo/provisional
  - seat 1 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed

### Episode 80515553 — our_win
- file: `80515553.json` (sha256 `1e73b4da9e67…`)
- agents: ['Kerminal', 'Yohei Nakajima'], rewards: [-1, 1], steps: 138
  - seat 0 (opponent, Kerminal): deck=`opponent_unknown` uniq=28 archetype=unknown_ex_tempo/provisional
  - seat 1 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed

### Episode 80516161 — our_win
- file: `80516161.json` (sha256 `7f61ae195d43…`)
- agents: ['AMIBEN', 'Yohei Nakajima'], rewards: [-1, 1], steps: 196
  - seat 0 (opponent, AMIBEN): deck=`opponent_unknown` uniq=15 archetype=unknown_ex_tempo/provisional
  - seat 1 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed

### Episode 80590776 — self_mirror
- file: `80590776.json` (sha256 `dfc86be53089…`)
- agents: ['Yohei Nakajima', 'Yohei Nakajima'], rewards: [1, -1], steps: 148
  - seat 0 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed
  - seat 1 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed

### Episode 80591511 — our_loss
- file: `80591511.json` (sha256 `fbf9cdb88cfd…`)
- agents: ['Latitu', 'Yohei Nakajima'], rewards: [1, -1], steps: 97
  - seat 0 (opponent, Latitu): deck=`opponent_unknown` uniq=14 archetype=unknown/unknown
  - seat 1 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed

### Episode 80592173 — our_win
- file: `80592173.json` (sha256 `fa1193d84042…`)
- agents: ['Yohei Nakajima', 'Roman Tamrazov'], rewards: [1, -1], steps: 112
  - seat 0 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed
  - seat 1 (opponent, Roman Tamrazov): deck=`opponent_unknown` uniq=17 archetype=unknown_ex_tempo/provisional

### Episode 80592831 — our_loss
- file: `80592831.json` (sha256 `d56ebe9c21be…`)
- agents: ['Yohei Nakajima', 'Leopard Jaguar'], rewards: [-1, 1], steps: 23
  - seat 0 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed
  - seat 1 (opponent, Leopard Jaguar): deck=`opponent_unknown` uniq=17 archetype=unknown/unknown

### Episode 80593320 — our_loss
- file: `80593320.json` (sha256 `7ebd6047ff2e…`)
- agents: ['Yohei Nakajima', 'Kazato Takahashi'], rewards: [-1, 1], steps: 91
  - seat 0 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed
  - seat 1 (opponent, Kazato Takahashi): deck=`opponent_unknown` uniq=24 archetype=unknown/unknown

### Episode 80594489 — our_loss
- file: `80594489.json` (sha256 `4cdeb3499ece…`)
- agents: ['AnDy Trần', 'Yohei Nakajima'], rewards: [1, -1], steps: 63
  - seat 0 (opponent, AnDy Trần): deck=`opponent_unknown` uniq=9 archetype=water_kyogre_abomasnow_maxbelt/confirmed
  - seat 1 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed

### Episode 80595014 — our_loss
- file: `80595014.json` (sha256 `3edbc7016380…`)
- agents: ['Shota Yamazaki', 'Yohei Nakajima'], rewards: [1, -1], steps: 67
  - seat 0 (opponent, Shota Yamazaki): deck=`opponent_unknown` uniq=9 archetype=water_kyogre_abomasnow_maxbelt/confirmed
  - seat 1 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed

### Episode 80622626 — self_mirror
- file: `80622626.json` (sha256 `387334c7de39…`)
- agents: ['Yohei Nakajima', 'Yohei Nakajima'], rewards: [1, -1], steps: 126
  - seat 0 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed
  - seat 1 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed

### Episode 80622745 — our_win
- file: `80622745.json` (sha256 `09e66f24e9a2…`)
- agents: ['mewworldorder', 'Yohei Nakajima'], rewards: [-1, 1], steps: 110
  - seat 0 (opponent, mewworldorder): deck=`opponent_unknown` uniq=20 archetype=unknown/unknown
  - seat 1 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed

### Episode 80623232 — our_loss
- file: `80623232.json` (sha256 `e5a5d2e4dfdc…`)
- agents: ['ﾖﾈｸﾗ ﾃﾝｾｲne251225', 'Yohei Nakajima'], rewards: [1, -1], steps: 110
  - seat 0 (opponent, ﾖﾈｸﾗ ﾃﾝｾｲne251225): deck=`opponent_unknown` uniq=17 archetype=unknown_ex_tempo/provisional
  - seat 1 (ours, Yohei Nakajima): deck=`v2_deck_energy_trim_light` uniq=11 archetype=water_kyogre_abomasnow_passive_mirror/confirmed

