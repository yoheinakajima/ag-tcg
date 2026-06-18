---
name: Card DB energy detection
description: How to recognize basic energy cards for copy-limit / deck-building checks in the ActiveGraph PTCG lab.
---

# Basic energy detection

`card_db.basic_features(cid)` returns a `is_energy` field that is **`False` for
every Basic {X} Energy id** (verified for ids 1-8, including the deck's default
{W} energy id 3). Do not trust `is_energy` to identify basic energy.

**Rule:** detect basic energy by NAME — `name.lower()` starts with `"basic "`
and ends with `" energy"` (helper: `generator._is_basic_energy(cid, card_db)`).
The deck's default energy `ENERGY_ID = 3` ({W}) is always treated as energy.

**Why:** the copy-limit guard (`_illegal_copy_counts`) must allow unlimited
copies of basic energy but cap every other card at 4. An earlier version
hard-coded only `cid == ENERGY_ID`, so a {G} chaos deck running Basic {G} Energy
(id 1) x28 was wrongly rejected as "exceeds 4 copies". Generator card-name maps
(`CARD_NAMES`) only cover the root deck's ids, so they cannot classify the other
basic-energy ids either — go through `card_db`.

**How to apply:** whenever building or validating a non-baseline deck (deck
variants, chaos full-replacement decks), pass `card_db` so basic energy of ANY
type is recognized. Confirmed basic energy ids: 1={G} 2={R} 3={W} 4={L} 5={P}
6={F} 7={D} 8={M}.

**cabt legality is by NAME, not id:** the real engine caps non-energy cards at 4
copies *per card name*. Two different prints sharing a name (e.g. Snorunt 103 and
860) together must stay <=4, even though each id is <=4. Keep chaos/variant decks
<=4 per name to survive the smoke run, not just <=4 per id.
