---
name: Unknown-EX tempo decomposition & card-name authority
description: How the unknown_ex_tempo bucket splits, and which source is authoritative for card id->name.
---

# Card id -> name: trust the card DB, not archetypes.yaml

**Rule:** `data/cards/EN_Card_Data.csv` (cols `Card ID`, `Card Name`, `Category`,
`Rule`, ...) is the authoritative card id->name source. The
`evidence_card_names` list inside `data/meta_replays/archetypes.yaml` is
positionally aligned to `evidence_card_ids` and was found to have **678/756
swapped** for the `unknown_ex_tempo` bucket.

- 678 = **Mega Lucario ex** (Rule: "Mega Pokémon ex")
- 756 = **Mega Kangaskhan ex**
- 121 = Dragapult ex, 269 = Iono's Bellibolt ex

**Why:** archetypes.yaml had 678→"Mega Kangaskhan ex", 756→"Mega Lucario ex",
the opposite of the card DB. Labeling subfamilies from archetypes.yaml names
would have mislabeled the two Mega lines.

**How to apply:** when naming archetypes/subfamilies from card ids, resolve names
via EN_Card_Data.csv, not the evidence_card_names field. Never commit that CSV.

# unknown_ex_tempo decomposition (5 real-opponent episodes, opponent at p0)

Each opponent deck carries a distinct signature Mega/ex line (>=2 copies):
- mega_lucario_ex_tempo: 80504942 (our_win), 80506042 (our_loss)  [678 x4 / x3]
- mega_kangaskhan_energy_stack: 80505567 (our_loss)               [756 x4]
- dragapult_ex: 80515553 (our_win)                                [121 x3]
- lightning_bellibolt: 80516161 (our_win)                         [269 x3]

Split the Pass-12 capped 0.60 unknown weight by replay frequency: lucario 0.24,
kangaskhan 0.12, dragapult 0.12, bellibolt 0.12. Confirmed metal/maxbelt stay
0.20 each. Subfamilies are all **provisional** (small sample, single pass);
`generic_unknown_ex_tempo` is retained as the low-confidence fallback category.
Signature card ids all come from the existing evidence_card_ids — no invention.
