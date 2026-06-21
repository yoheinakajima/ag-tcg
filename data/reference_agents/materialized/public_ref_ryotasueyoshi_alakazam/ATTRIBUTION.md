# Attribution — 🤖 Rule-based, not psychic: Alakazam (Best: 5th)

- **Original author:** sue124 (`ryotasueyoshi`) on Kaggle
- **Source kernel:** [ryotasueyoshi/rule-based-not-psychic-alakazam-best-5th](https://www.kaggle.com/code/ryotasueyoshi/rule-based-not-psychic-alakazam-best-5th)
- **Source kind:** public_competitor_notebook
- **Deck archetype:** Alakazam (rule-based)
- **Competition:** pokemon-tcg-ai-battle
- **Optional:** yes

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

- submission.tar.gz: `616b13b0582f58641ce25b7f284729b97d02caebaa1f3da6429e5d589cc34b33` (1060972 bytes)
- main.py: `df4d597f593950b0d0c372f3e0bb26c182c4116648977f15adbb329a6ba922f4`
- deck.csv: `7b413177e5077777f2178143839c0155b03b92bbc8b3a6607621a7d43f351141`
- cg SDK signature: `cd7799a3e539cb72034835028f52ffa2a20e83733213f2a9d5a0835d3436798d`

## License

Public Kaggle kernel (is_private=false). Used here strictly as a benchmark opponent with attribution to the original author; not redistributed as our own work. The cg SDK / libcg.so / official card data are kept gitignored. See the kernel page for the author's stated license/terms.

