# Attribution — A Sample Rule-Based Agent Iono's Deck

- **Original author:** Kiyota (`kiyotah`) on Kaggle
- **Source kernel:** [kiyotah/a-sample-rule-based-agent-iono-s-deck](https://www.kaggle.com/code/kiyotah/a-sample-rule-based-agent-iono-s-deck)
- **Source kind:** host_public_sample
- **Deck archetype:** Iono's deck
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

- submission.tar.gz: `5c896471559cfdfa914f19e9ee7d512136a34c5825337baf53a039e525620e70` (497632 bytes)
- main.py: `9fa360307e0b9ccd4cd8469aad50c93872468c8dfa8ff8ebb6718cacf9faa8fa`
- deck.csv: `e36d46c5bcafdef8a5d0e6caeb34dd8db09119c62d8fb67c99e89e7eed39f974`
- cg SDK signature: `cd7799a3e539cb72034835028f52ffa2a20e83733213f2a9d5a0835d3436798d`

## License

Public Kaggle kernel (is_private=false). Used here strictly as a benchmark opponent with attribution to the original author; not redistributed as our own work. The cg SDK / libcg.so / official card data are kept gitignored. See the kernel page for the author's stated license/terms.

