# Attribution — A Sample Rule-Based Agent Dragapult ex Deck

- **Original author:** Kiyota (`kiyotah`) on Kaggle
- **Source kernel:** [kiyotah/a-sample-rule-based-agent-dragapult-ex-deck](https://www.kaggle.com/code/kiyotah/a-sample-rule-based-agent-dragapult-ex-deck)
- **Source kind:** host_public_sample
- **Deck archetype:** Dragapult ex
- **Competition:** pokemon-tcg-ai-battle
- **Optional:** no

## What this is

A public Kaggle rule-based agent for the Pokémon-TCG AI Battle competition, materialized from the kernel's published `submission.tar.gz` output (the canonical cg_typed layout: `main.py` + `deck.csv` + the `cg` SDK).

## How we use it

Registered in our tournament with pool status **`external_reference`** as a **benchmark opponent only**. It is:
- never uploaded or submitted to Kaggle
- never entered in the submission queue / promoted / family-champion
- never mutated; not part of any mutation lineage
- never counted toward the active-candidate cap or 'our best' rankings
- excluded from the lifecycle manager

Internal win-rates against it are LOCAL diagnostics, not Kaggle leaderboard scores.

## Provenance (sha256)

- submission.tar.gz: `152fa4e9b1322b98c50d696299b548fdf0e95e46be31ef7ce625612022d386d4` (500419 bytes)
- main.py: `ef8936859fd215e6c704071042e5438d55e2e972b8f1806fb6eddbd03027e0b9`
- deck.csv: `30c8c7365c75f38fd6e7e1d8543c42ce7055ed6fd1c6e9eb244e44484b78e724`
- cg SDK signature: `cd7799a3e539cb72034835028f52ffa2a20e83733213f2a9d5a0835d3436798d`

## License

Public Kaggle kernel (is_private=false). Used here strictly as a benchmark opponent with attribution to the original author; not redistributed as our own work. The cg SDK / libcg.so / official card data are kept gitignored. See the kernel page for the author's stated license/terms.

