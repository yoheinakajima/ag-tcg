# Card & Deck Graph

How card metadata is ingested, tagged, validated, and analysed.
Source: `src/ptcg_activegraph/cards/`, `src/ptcg_activegraph/decks/`,
`src/ptcg_activegraph/graph/card_graph.py`, `.../deck_graph.py`.

## Card ingestion (`cards/card_db.py`)

`load_card_db()` tries sources in priority order:

1. **Local CSV** — `data/cards/EN_Card_Data.csv`, `data/cards/JP_Card_Data.csv`,
   or `EN_Card_Data.csv` / `JP_Card_Data.csv` at the repo root.
2. **cabt API** — `all_card_data()` (and `all_attack()`) when importable.
3. **Empty placeholder** — an empty DB so everything still runs.

The loader is schema-tolerant: it normalizes a `card_id` and `name` from common
column names and keeps all original columns.

`CardDB` exposes:

* `get(card_id)` — record or `None`.
* `all()` — all records.
* `search_name(name)` — exact then substring match.
* `basic_features(card_id)` — roles + coarse type flags (`is_basic`,
  `is_evolution`, `is_energy`, `is_trainer`, `is_attacker`).

## Role tagging (`cards/role_tags.py`)

Heuristic, best-effort over whatever text/fields a card exposes. Tags:

```
Basic Pokémon  Evolution  Attacker  Draw  Search  Energy acceleration
Switch/retreat support  Recovery  Disruption  Stadium  Energy  Trainer  Unknown
```

Tagging never raises and falls back to `Unknown`. As the official schema becomes
known, tighten the keyword/field rules.

## CardGraph (`graph/card_graph.py`)

Nodes are cards; edges are best-effort evolution relations (`evolves_from` →
child). `CardGraph.from_card_db(db)` builds it; `neighbors(card_id)` returns the
cards a Pokémon can evolve into. This is the seed for synergy/combo analysis.

## DeckGraph (`graph/deck_graph.py`)

A deck as a multiset of cards plus derived **role composition**:

```python
from ptcg_activegraph.graph.deck_graph import DeckGraph
g = DeckGraph.from_card_ids(card_ids, card_db=db)
g.summary()   # size, unique_cards, role_totals, top_cards
```

## Deck features (`decks/deck_features.py`)

`compute_deck_features(card_ids, card_db)` estimates Pokémon / Basic / Evolution
/ Trainer / Energy / Attacker counts and a rough **0..1 bot-playability score**
(rewards having basics, energy, and attackers; sane size). Advisory only.

## Deck validation (`decks/validator.py`)

Hard rules (errors): **exactly 60 cards**, **every entry an integer id**.
Soft rules (warnings, need card metadata): max copies (4, Energy exempt when
detectable), at least one Basic Pokémon.

```python
from ptcg_activegraph.decks import validate_deck
result = validate_deck(card_ids, card_db=db)
result.valid, result.errors, result.warnings, result.counts, result.features
```

## Deck IO (`decks/deck_io.py`)

`load_deck(path)` accepts newline/comma-separated integers, an optional header,
`#` comments, or a CSV with an `id`/`card_id` column. `save_deck(path, ids)`
writes the canonical one-id-per-line form.

## Baseline / placeholder decks (`decks/baseline_decks.py`)

We do **not** invent real card IDs. Without a card DB, `make_placeholder_deck`
returns a structurally-valid repeated-id deck (for exercising the pipeline). With
a card DB, it prefers real basics/energy so the deck is at least plausibly
playable.

## Future deck optimizer

With real data + the simulator, the lab can: build a candidate pool from role
balance heuristics, run a deck tournament (`sim/tournament.py`), record per-deck
win rates (`DeckPerformanceProjection`), and promote the best decklist via a
`DECK_CONSTRUCTION` patch plan (seam: `deck_list`).
