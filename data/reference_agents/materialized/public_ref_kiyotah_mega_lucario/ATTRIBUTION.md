# Attribution — A Sample Rule-Based Agent Mega Lucario ex Deck

- **Original author:** Kiyota (`kiyotah`) on Kaggle
- **Source kernel:** [kiyotah/a-sample-rule-based-agent-mega-lucario-ex-deck](https://www.kaggle.com/code/kiyotah/a-sample-rule-based-agent-mega-lucario-ex-deck)
- **Source kind:** host_public_sample
- **Deck archetype:** Mega Lucario ex
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

- submission.tar.gz: `56b15c91425902651e539f7c8157dd417fe2c834693c69ea8df9ed48f4bc5c22` (498154 bytes)
- main.py: `ab8563b67b88b3666c2ff9c308505085a84fdac676c194c5b484d8544478c3b2`
- deck.csv: `406e2e9bd6ae82b8008b16ee64ffcbb58e4a50cd6bc36e33ae655456c6b9afee`
- cg SDK signature: `cd7799a3e539cb72034835028f52ffa2a20e83733213f2a9d5a0835d3436798d`

## License

Public Kaggle kernel (is_private=false). Used here strictly as a benchmark opponent with attribution to the original author; not redistributed as our own work. The cg SDK / libcg.so / official card data are kept gitignored. See the kernel page for the author's stated license/terms.

