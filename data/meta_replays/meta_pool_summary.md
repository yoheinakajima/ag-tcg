# Meta pool summary (Pass 11B)

- coverage status: **usable**
- active control (live): **league_water_anti_disruption_pivot_v1** @ 520.8 (complete)
- confirmed opponent archetypes: metal_ex_zacian_ramp, water_kyogre_abomasnow_maxbelt
- provisional archetypes: unknown_ex_tempo
- blocked archetypes: none

## Evaluation weights (opponent frequency)
- metal_ex_zacian_ramp: 0.0667
- unknown: 0.2667
- unknown_ex_tempo: 0.4667
- water_kyogre_abomasnow_maxbelt: 0.2

## Archetypes
| key | confidence | ours | surrogate deck | weight |
|---|---|---|---|---|
| metal_ex_zacian_ramp | confirmed | no | `data/meta_replays/decks/80503804_p1_deck.csv` | 0.0667 |
| unknown | unknown | no | `data/meta_replays/decks/80591511_p0_deck.csv` | 0.2667 |
| unknown_ex_tempo | provisional | no | `data/meta_replays/decks/80504942_p0_deck.csv` | 0.4667 |
| water_kyogre_abomasnow_maxbelt | confirmed | no | `data/meta_replays/decks/80504288_p0_deck.csv` | 0.2 |
| water_kyogre_abomasnow_passive_mirror | confirmed | yes | `data/meta_replays/decks/80374966_p0_deck.csv` | None |

## Conclusion
Meta coverage is USABLE: 2 opponent archetype(s) are CONFIRMED from real extracted replays (metal_ex_zacian_ramp, water_kyogre_abomasnow_maxbelt), and 1 provisional bucket(s) (unknown_ex_tempo) hold real surrogate decks but lack a precise named signature (47% of opponent weight). Local cabt self-play is runnable, so candidates can be evaluated against these surrogates — but the provisional bucket means the eval is not a fully named meta and no candidate is auto-promotable.
