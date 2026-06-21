# Attribution — A Sample Rule-Based Agent Mega Abomasnow ex Deck

- **Original author:** Kiyota (`kiyotah`) on Kaggle
- **Source kernel:** [kiyotah/a-sample-rule-based-agent-mega-abomasnow-ex-deck](https://www.kaggle.com/code/kiyotah/a-sample-rule-based-agent-mega-abomasnow-ex-deck)
- **Source kind:** host_public_sample
- **Deck archetype:** Mega Abomasnow ex
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

- submission.tar.gz: `2ccde9fdb8a8c554e17d21d75bc6d89b9d6a0e859fdf9e9d59bbbaae594a542e` (496935 bytes)
- main.py: `d1ef4a86413b7f548270657385c6d5c3cb114b473082cd04e2a0f1733158482b`
- deck.csv: `7af2d7e111c084da535b89758730b3fd6cbb7c0543a9444499c5b61efdc8aecd`
- cg SDK signature: `cd7799a3e539cb72034835028f52ffa2a20e83733213f2a9d5a0835d3436798d`

## License

Public Kaggle kernel (is_private=false). Used here strictly as a benchmark opponent with attribution to the original author; not redistributed as our own work. The cg SDK / libcg.so / official card data are kept gitignored. See the kernel page for the author's stated license/terms.

