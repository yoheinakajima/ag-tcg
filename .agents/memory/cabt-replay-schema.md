---
name: cabt replay step/option schema
description: How to honestly decode cabt Kaggle replay JSONs for postmortems without overclaiming
---

# cabt replay decoding (Pokémon TCG AI)

Raw replay JSON: `steps[i][seat]` has `action` (list of chosen option indices),
`observation.select` (legal options), `status` (ACTIVE/INACTIVE/INVALID), `reward`.
Top-level `rewards` list: `+1` win / `-1` loss / `0` draw per seat.

**Option `type` codes** (see `src/ptcg_activegraph/analysis/action_resolver.py`
`OPTION_TYPE_CLASS`): 13=attack(`attackId`), 8=attach_energy, 7=play_from_hand,
9=use_ability, 10=play_in_play, 6=move_energy, 3=select_card, 12/14=end_turn,
0/1/2=effect_choice. A deck-selection step has a ~60-len option list (skip via len>40).

**Final board state**: walk steps in reverse for `observation.current` with a
populated `players`. Each player has `prize` (a LIST of remaining prize cards →
`len()` = prizes remaining; 6 means took 0), `bench` (list), `active`.

**Loss-condition heuristic** (honest): opp took ≥4 prizes (their remaining ≤2) →
prize_race_loss; opp took only ~1 and our bench=0 → no_pokemon_loss. Keep terminal
condition separate from contributing factors (very_late_first_attack, attacks not
converting to prizes) — do NOT let pacing factors overwrite the terminal class.

**Honesty hard rule:** attacks expose only a NUMERIC `attackId` — attack name,
Phantom-Dive/spread target, Dusknoir line, Boss/gust are NOT observable from the
option schema. Never claim spread-targeting misplays or invent card IDs.

**Duplicate Kaggle submissions:** `kaggle competitions submissions -v` lists the
SAME filename multiple times (history). When indexing by filename, prefer the
complete row with the highest publicScore, else you get a stale error/null row.
