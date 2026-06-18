# policy_mega_signal_v2

- **Seam:** policy.mega_signal_evolution_search
- **Kind:** combo    **Archetype:** setup_evolution
- **Parent:** v1_kaggle_349_8
- **Stage:** pass5_scout

## Hypothesis
Mega Signal (1145) line-coherence: only fetch Mega Abomasnow ex (723) when its Snover (722) basic is already on board; otherwise prefer fetching Snover first so the evolution line is not stranded (the step-17 replay failure: Mega fetched with no Snover line).

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 10 (seat-swap: True)
- wins / losses / draws: 2 / 8 / 0
- raw win rate: 0.20    adjusted win rate: 0.20
- as P0: 1/5 (rate 0.20); as P1: 1/5 (rate 0.20)
- seat balance delta (P0-P1): 0.00
- attack rate: 0.66    pass rate: 0.01
- crashes / timeouts / fallbacks: 0 / 0 / 0
