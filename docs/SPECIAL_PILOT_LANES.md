# Special-Pilot Lanes (Pass 34)

> LOCAL / no upload. This document describes the **special-pilot lane** introduced
> in Pass 34 and why two of the four intake decks belong to it. It is **plan-first**:
> no special pilot is wired in Pass 34, so the special-lane decks are
> `blocked_from_league` and their plans are `executable: false`.

## Why two lanes?

Pass 34 ingests four new deck families and splits them into two lanes by how well
the **shared deck-agnostic generic pilot** can drive them:

- **Normal lane** — simple Basic-attacker / prize-racing decks the generic pilot
  pilots correctly. League-eligible.
  - `mono_lightning_miraidon_easy` (Mono-Lightning Miraidon ex)
  - `diamond_toolbox_diancie` (Diamond Toolbox — Mega Diancie ex, mono-Psychic)

- **Special-pilot lane** — decks whose win condition is **not** prize-racing
  (passive status lock, deck-out / mill control). The generic pilot mis-pilots
  them. Blocked from league until a dedicated pilot exists.
  - `toxic_trap_poison_lock` (Pecharunt poison lock)
  - `deckout_carousel_durant_v2` (Durant ex mill-control)

## The evidence (Part G live smoke)

Each candidate ran one live `cabt` game with **both seats = the candidate** under
the generic pilot:

| deck | lane | deck legal? (a seat reached DONE) | generic pilot illegal? (a seat INVALID) |
|---|---|---|---|
| mono_lightning_miraidon_easy | normal | yes | no |
| diamond_toolbox_diancie | normal | yes | no |
| toxic_trap_poison_lock | special | **yes** | **yes** |
| deckout_carousel_durant_v2 | special | **yes** | **yes** |

The split is the key honest finding: for the special-lane decks **the deck is
legal** (a seat reaches `DONE` with the exact 60-card list) but **the generic
pilot emits an illegal gameplay action** piloting the non-racing win condition
(the other seat goes `INVALID`). That is a *pilot* mis-fit, not a
*deck-construction* fault.

## What a special pilot must do

See `data/fixtures/pass34_special_pilot_plans.yaml` for per-deck win conditions
and required behaviors. In short:

- **Toxic Trap:** value establishing/maintaining the poison/status lock over KOs;
  never break the lock to chase a prize.
- **Deck-Out Carousel:** value opponent deck depletion as the win metric; wall and
  recycle disruption; avoid self-deckout.

## Promotion gate (not done in Pass 34)

A special-lane deck becomes league-eligible only after a dedicated pilot:

1. drives the deck through a clean `cabt` game reaching `DONE` on **both** seats
   (no `INVALID`/`ERROR`), and
2. passes the standard tarball + entrypoint validators.

Until then these decks stay `blocked_from_league` and their plans are
`executable: false`. **No special pilot is built or run in Pass 34.**

## Part-I diagnosis (refreshed)

Live-smoke diagnosis of the two special-lane decks (generic pilot, both seats = candidate). Both have LEGAL 60-card decklists; both are blocked by the PILOT, not the deck:

| deck | decklist_valid | built | smoke_valid | blocked_by | should_enter_sprint |
|---|---|---|---|---|---|
| toxic_trap_poison_lock | yes | yes | no | pilot | yes |
| deckout_carousel_durant_v2 | yes | yes | no | pilot | yes |

### Required pilot hooks & next step

- **toxic_trap_poison_lock** — missing hooks: prioritize establishing and maintaining the poison/status lock over KOs, avoid actions that drop the lock to chase a prize, manage Binding Mochi / Dangerous Laser disruption timing, only attack when it does not break the lock; first fixture needed: A clean cabt game where the special pilot drives this deck and reaches DONE on BOTH seats (no INVALID). Not run in Pass 34.
- **deckout_carousel_durant_v2** — missing hooks: value opponent deck depletion as the win metric, preserve the wall and avoid trading prizes, sequence Judge / Lacey / Acerola disruption to accelerate the deck-out, avoid self-deckout (manage own draw); first fixture needed: A clean cabt game where the special pilot drives this deck and reaches DONE on BOTH seats (no INVALID). Not run in Pass 34.

_LOCAL / no upload. Diagnosis is internal smoke evidence, NOT a Kaggle result._
