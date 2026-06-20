---
name: EN_Card_Data.csv classification quirks
description: Non-obvious quirks in the local EN_Card_Data card CSV that break naive metadata classification.
---

The local `data/cards/EN_Card_Data.csv` (gitignored, never committed) drives the
typed layer's per-card metadata. Two quirks bite naive parsing:

1. **"Pokémon Tool" contains the substring "pok".** The card-type column
   (`Stage (Pokémon)/Type (Energy and Trainer)`) holds values like
   "Basic Pokémon", "Stage 1 Pokémon", "Pokémon Tool", "Item", "Supporter",
   "Stadium", "Basic Energy". A substring `"pok" in st` check therefore
   mis-buckets Pokémon **Tools** (e.g. Powerglass, Binding Mochi) as Pokémon.
   **Why:** caused tools to be tagged `card_type=pokemon`.
   **How to apply:** classify in this order — energy first, then trainer markers
   (item/supporter/stadium/tool/technical machine), then `"pok"` → pokemon.
   Real Pokémon rows carry no trainer marker so they fall through correctly.

2. **Dragon energy type renders as the CJK glyph `竜`, not a `{N}` symbol.**
   So `energy_type` for Raging Bolt / Dragapult lines is the literal string
   `"竜"`. Profile `energy_types` use English color names, so a Dragon attacker's
   type-match will simply not fire — which is acceptable (attach falls back to
   role-weight/active selection). Do NOT special-case `竜` into a fake color
   match; honest non-match is correct.
