# Meta Engine Strategies

Inferred competitive-meta strategy tracks for the Kaggle PTCG environment, kept
stable across passes. These are the labelling vocabulary used by
`scripts/extract_meta_archetypes.py` and the design backlog for future *engine*
decks (decks with a real setup/payoff plan rather than a single linear line).

This document is **strategy scaffolding only**. Pass 7B does not evaluate any
meta engine candidate. Card names below come from prior inferred analysis and
the project spec; the extraction scripts must **not** invent numeric card IDs
from card-name text — unknown ids stay `unknown`.

## Track 1 — Alakazam / Dunsparce Psychic setup-control

- low energy count
- high search / tutor density
- Abra / Kadabra / Alakazam evolution line
- Dunsparce / Dudunsparce draw engine
- Rare Candy / Dawn / Hilda / Buddy-Buddy Poffin style setup
- disruption after setup: Boss's Orders, Enhanced Hammer, stadium pressure
- **policy seam:** missing-piece planner (what evolution/tool is missing and
  which tutor fetches it next)

## Track 2 — Bellibolt / Kilowattrel Lightning ramp

- electric evolution / ramp engine
- Tadbulb / Bellibolt ex attacker
- Wattrel / Kilowattrel acceleration
- Canari / Levincia / Ultra Ball / Lillie's Determination search engine
- recovery resources
- **policy seam:** ramp plan and exact tutor target selection

## Track 3 — Generic engine-deck pattern

- lower energy
- high search
- high redundancy
- plan-state tracking
- search target logic
- discard protection for plan pieces
- bench-width setup
- first meaningful attack turn
- disruption layered after setup
- **policy seam:** plan-state tracker + discard-protection for plan pieces

## Track 4 — Chaos as engine-supported disruption

Chaos must not be random; it must have a payoff engine driven by **visible**
opponent signals only.

- Froslass hand-size payoff uses visible opponent `handCount`
- Durant / mill uses visible opponent `deckCount`
- Bench-bloat uses visible opponent bench count
- Status chaos uses visible status flags
- **policy seam:** payoff condition tied to an observable opponent signal (no
  hidden-information assumptions)

## How the scripts use these tracks

`extract_meta_archetypes.py` matches each parsed replay's deck skeleton and
early-game policy fingerprint against these four tracks and assigns the closest
label (or `unclassified` when evidence is too thin). Matching uses card
**names/roles** present in the source data, never fabricated ids. Every
assignment carries a confidence and an uncertainty note when coverage is
partial.

## Out of scope for Pass 7B

- Building or evaluating meta engine candidate decks.
- Any Kaggle upload / submission.
- Inventing card IDs or deck lists not present in real replay data.
