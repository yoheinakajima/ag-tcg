# ActiveGraph — Pokémon TCG Strategy Canvas (Pass 17)

> **LOCAL ONLY.** Nothing in this pass is uploaded to Kaggle or pushed to GitHub.
> The internal deck league is **not** a Kaggle leaderboard and its win rates do
> **not** predict Kaggle results — opponents are our own decks piloted by the same
> generic core pilot. Card ids are validated against `data/cards/EN_Card_Data.csv`
> (gitignored, never committed). No invented ids.

## 1. Purpose

Pass 17 turns the single proven Water deck into a small **internal deck league**:
several legal decks, each piloted by the **same generic core pilot** plus a minimal
per-deck **playbook** (card roles only). We run a round-robin among them to learn
which archetypes the current generic pilot can actually pilot, and where it breaks
down — a **deck/pilot compatibility** study, not a tournament for ranking strength.

## 2. The pilot model

- **Generic core pilot.** One brain. Generic competence comes from mechanics/score
  evaluation in the base agent, not from hand-tuned per-card logic.
- **Playbooks add roles, not rules.** A playbook tags each card
  (`primary_basic_attacker`, `setup_basic`, `evolution_payoff`, `search`, `draw`,
  `disruption`, `stadium`, `deckout_or_mill`, …) and expresses light preferences
  (what to put active, what to search, what to discard). It never hard-codes a
  scripted line.
- **Runtime contexts** decide which decision points the pilot refines:
  - `(7, 8)` = search + discard refinement (faithful Water reference).
  - `(1, 2, 7, 8, 38)` = also setup-active / setup-bench / draw, so a new deck's
    setup preferences (e.g. "prefer Raging Bolt active") can express themselves.
- **Broad Main stays delegated** to the base policy. The pilot only overrides the
  seams listed above.

## 3. Deck archetypes in the league

| Deck | Archetype | Why it is in the study | League |
|---|---|---|---|
| `league_water_core_reference` | Tempo + evolution payoff | Proven clean reference (v2) | ✅ in |
| `league_raging_bolt_ogerpon` | Fast basic aggro | Low evolution burden; tests early attach + attack | ✅ in |
| `league_dragapult_spread` | Stage-2 evolution control | Tests evolution sequencing (Dreepy→Drakloak→Dragapult ex) | ✅ in |
| `league_durant_deckout_carousel` | Deck-out / mill chaos | Needs special mill triggers the pilot lacks | ⛔ scout-only |

A historical reference (`core_pilot_water_v2_runtime`) may also be entered as a
separate fixed yardstick.

### Why Durant is blocked
Durant's win condition is decking the opponent out, which requires triggers the
generic pilot does **not** implement: keep Durant ex benched until its mill is set
up, use Deino/Zweilous as the damage sponge, prioritize Neutralization Zone, loop
the mill engine, and **never race prizes**. Piloted generically it would chase KOs
and invert its own plan, so it is built and validated for legality only and kept
out of the league. (See `playbooks/pass17_durant_deckout_carousel.yaml`.)

## 4. Deck construction rules

- Exactly **60 cards**. At most **4 copies** of any non-basic-energy card; basic
  energy is unlimited.
- Decks start from a hand skeleton, then are filled to 60 **only** with validated
  consistency cards or basic energy. Every filler is documented in
  `experiments/deck_ideas.yaml`.
- Every id is checked against `EN_Card_Data.csv` before a deck is built — no
  invented ids, ever.

## 5. Compatibility framework (what the league measures)

For each buildable deck we ask:
- **Does it run at all?** No crashes / timeouts / illegal actions in live cabt.
- **Adjusted win rate** vs the other decks (seat-swapped to cancel first-player bias).
- **Where does the generic pilot fit the deck, and where does it fight it?**
  - Aggro: does it attach and attack early, or sit and draw?
  - Evolution: does it build the line, or orphan its Stage 2?
  - Mill: (Durant) cannot be expressed → blocked.
- Honest gaps are recorded as **compatibility findings**, not hidden (e.g. the pilot
  does not color-match energy, does not place spread damage, has no mill plan).

## 6. Pipeline (this pass)

1. Strategy canvas + deck ideas → **this file** + `experiments/deck_ideas.yaml`.
2. Validate ids / legality → `scripts/validate_deck_ideas.py`.
3. Minimal playbooks → `playbooks/pass17_*.yaml`.
4. Build candidates → `data/submissions/candidates_pass17/<id>.tar.gz`
   (Durant built but blocked).
5. Validation gates + live smoke.
6. Internal round-robin league (seat-swapped, watchdog).
7. Deck/pilot compatibility analysis.
8. Ranked report + next action.

## 7. League results

Round-robin, seat-swapped (5 games/seat × 2 seats = 10 games/pairing), watchdog +
global budget. Participants: the 3 league-eligible candidates plus the historical
`core_pilot_water_v2_runtime` as a fixed yardstick. Durant is **blocked** (its live
self-smoke is INVALID — see §5). Full data:
`data/experiments/pass17_internal_league.{json,md}`,
`pass17_league_matrix.csv`, `pass17_league_rankings.{json,md}`.

> These are **internal compatibility** numbers, **not** Kaggle results — every
> opponent is one of our own decks run by the same generic pilot.

| rank | deck | role | W-L-D | adj win rate | rating |
|---|---|---|---|---|---|
| 1 | `league_water_core_reference` | candidate | 23-7-0 | **0.767** | good |
| 2 | `league_dragapult_spread` | candidate | 19-11-0 | **0.633** | good |
| 3 | `core_pilot_water_v2_runtime` | reference | 18-12-0 | 0.600 | (anchor) |
| 4 | `league_raging_bolt_ogerpon` | candidate | 0-30-0 | **0.000** | poor |

**Findings (deck/pilot compatibility — `pass17_deck_pilot_compatibility.{md,json}`):**

- **Tempo/evolution transfers.** The Water reference (the deck the pilot was tuned
  around) and Dragapult (Stage-2 evolution) are both piloted *well* — evolution
  sequencing carries over. Dragapult even beats the historical anchor.
- **Aggro does not transfer.** `league_raging_bolt_ogerpon` plays every game to a
  **legal finish** (0 invalids/timeouts/crashes) yet wins **0 of 30**. The generic
  pilot does not color-match energy and has no attack-first bias, so Raging Bolt
  ex's discard-scaling attack never comes online before it is out-raced. This is a
  **pilot-fit failure, not a deck-legality failure** — strength ≠ fit.
- **Mill is out of reach.** Durant cannot even produce a legal game under the
  generic pilot; it is blocked, not ranked.

**Next action:** before any Kaggle probe, add an aggro playbook (early energy
color-matching + attack-first bias) and re-run the league to see whether
`league_raging_bolt_ogerpon` becomes pilotable. No candidate is uploaded.

## 8. Guardrails

NO Kaggle upload/submit. NO GitHub push. Root `main.py` / `deck.csv` stay
byte-identical to the v1 baseline. Tarballs contain only top-level `main.py` +
`deck.csv`. stdlib-only runtime. Card CSV / raw replays / credentials never
committed.
