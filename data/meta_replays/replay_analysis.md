# Replay analysis (Pass 11B)

- replays analyzed: **19**
- record (by our seat): **5W / 10L / 0D**, self-mirrors: 4, other: 0
- fast losses (≤60 steps): 80503804, 80505567, 80592831
- long/deckout games: 80374966, 80504942, 80506042, 80516161, 80590776, 80592173, 80622626

## Recurring failure tags
- stuck_on_basic_snover: 10
- loss_no_specific_tempo_tag: 4
- fast_loss: 3

## Opponent archetype patterns
- unknown_ex_tempo: 7
- unknown: 4
- water_kyogre_abomasnow_maxbelt: 3
- metal_ex_zacian_ramp: 1

## Per-replay
| episode | perspective | steps | opponent | tags |
|---|---|---|---|---|
| 80374966 | self_mirror | 136 | - | - |
| 80503687 | self_mirror | 79 | - | - |
| 80503804 | our_loss | 37 | metal_ex_zacian_ramp | fast_loss, stuck_on_basic_snover |
| 80504288 | our_loss | 134 | water_kyogre_abomasnow_maxbelt | stuck_on_basic_snover |
| 80504942 | our_win | 202 | unknown_ex_tempo | stuck_on_basic_snover |
| 80505567 | our_loss | 28 | unknown_ex_tempo | fast_loss, stuck_on_basic_snover |
| 80506042 | our_loss | 156 | unknown_ex_tempo | stuck_on_basic_snover |
| 80515553 | our_win | 138 | unknown_ex_tempo | stuck_on_basic_snover |
| 80516161 | our_win | 196 | unknown_ex_tempo | stuck_on_basic_snover |
| 80590776 | self_mirror | 148 | - | - |
| 80591511 | our_loss | 97 | unknown | stuck_on_basic_snover |
| 80592173 | our_win | 112 | unknown_ex_tempo | stuck_on_basic_snover |
| 80592831 | our_loss | 23 | unknown | fast_loss, stuck_on_basic_snover |
| 80593320 | our_loss | 91 | unknown | loss_no_specific_tempo_tag |
| 80594489 | our_loss | 63 | water_kyogre_abomasnow_maxbelt | loss_no_specific_tempo_tag |
| 80595014 | our_loss | 67 | water_kyogre_abomasnow_maxbelt | loss_no_specific_tempo_tag |
| 80622626 | self_mirror | 126 | - | - |
| 80622745 | our_win | 110 | unknown | - |
| 80623232 | our_loss | 110 | unknown_ex_tempo | loss_no_specific_tempo_tag |
