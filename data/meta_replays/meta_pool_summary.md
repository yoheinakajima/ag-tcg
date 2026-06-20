# Meta pool summary (Pass 11B)

- coverage status: **usable**
- active control (live): **league_water_anti_disruption_pivot_v1** @ 376.5 (complete)
- confirmed opponent archetypes: metal_ex_zacian_ramp, water_kyogre_abomasnow_maxbelt
- provisional archetypes: none
- blocked archetypes: none

## Evaluation weights (opponent frequency)
- metal_ex_zacian_ramp: 0.1
- unknown: 0.5
- water_kyogre_abomasnow_maxbelt: 0.4

## Archetypes
| key | confidence | ours | surrogate deck | weight |
|---|---|---|---|---|
| metal_ex_zacian_ramp | confirmed | no | `data/meta_replays/decks/80503804_p1_deck.csv` | 0.1 |
| unknown | unknown | no | `data/meta_replays/decks/80591511_p0_deck.csv` | 0.5 |
| unknown_ex_tempo | provisional | yes | `data/meta_replays/decks/80504942_p0_deck.csv` | None |
| water_kyogre_abomasnow_maxbelt | confirmed | no | `data/meta_replays/decks/80504288_p0_deck.csv` | 0.4 |
| water_kyogre_abomasnow_passive_mirror | confirmed | yes | `data/meta_replays/decks/80374966_p0_deck.csv` | None |

## Conclusion
Meta coverage is USABLE: 2 opponent archetype(s) are CONFIRMED from real extracted replays (metal_ex_zacian_ramp, water_kyogre_abomasnow_maxbelt), and 0 provisional bucket(s) (none) hold real surrogate decks but lack a precise named signature (0% of opponent weight). Local cabt self-play is runnable, so candidates can be evaluated against these surrogates — but the provisional bucket means the eval is not a fully named meta and no candidate is auto-promotable.
