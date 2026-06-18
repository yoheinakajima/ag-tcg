# ActiveGraph Core Pilot Architecture

The bottleneck after Pass 13 is **not** another deck variant. It is missing generic
Pokémon-TCG pilot competence that every deck needs: choosing the right active,
developing the bench, attaching energy/tools to the right target, evolving on time,
tying search to a board plan, not looping passive draw, not decking out, and
recovering after a knock-out.

This document defines a **layered** pilot so that generic skill lives in one place,
deck knowledge lives in a playbook, and card-specific hacks stay rare and explicit.

> **Design rule:** the generic layer is **mechanics / score based** (it knows
> "attacker", "basic", "tool", "deck count" — not "Kyogre"). The **playbook layer**
> supplies card *roles*. **Card-specific exceptions** are the last resort and must be
> few and explicit.

---

## Layer 0 — Submission safety (never crash)

The non-negotiable floor. Independent of any pilot logic.

- Deck-selection step (`current` and `select` both `None` / absent) returns **exactly 60**
  integer card ids.
- The agent **never raises** outward — any internal error degrades to a legal fallback.
- Every returned action is a list of **legal, in-range, de-duplicated** option indices that
  respects `minCount` / `maxCount`.
- A guaranteed-legal fallback action exists for every decision.

This layer already exists in the runtime (`agent()` wrapper + deck-return safety block) and
is **preserved unchanged** when the core pilot is compiled in.

## Layer 1 — State model (read the board safely)

Pure, total, never-raising readers over the observation. Maps the raw `obs` into a
**normalized board** the upper layers reason about.

- Zones: `active`, `bench`, `hand`, `deck`(count), `discard`, `prize`(count).
- Legal-option resolution: option → card id where possible (hand `area==2`, search-deck
  `area==1`), option → target where possible (`inPlayArea` / `inPlayIndex`).
- Board summaries: deck count, hand count, bench count/space, status flags, in-play card ids.

Normalized board contract (the single shared structure for the upper layers, the fixtures,
and the compiled runtime):

```
board = {
  "active":     card | None,
  "bench":      [card, ...],
  "bench_max":  int,            # default 5
  "hand":       [card, ...],
  "deck_count": int,
  "discard":    [card, ...],
  "prize_count":int,
  "opponent_active": card | None,
}
card = {"card_id": int, "hp": int?, "is_basic": bool?, "energy": int?, "has_tool": bool?, "stage": str?}
option = {"card_id": int?, "is_attack": bool?, "is_draw_search": bool?,
          "damage": int?, "knocks_out": bool?, "target_card_id": int?}
```

## Layer 2 — Generic pilot (deck-agnostic competence)

Mechanics/score based. Knows roles, not card names. Each primitive scores legal options and
picks the best; ties break deterministically (lowest card id, then lowest index).

- **choose active** — prefer a high-HP basic attacker over a fragile setup basic.
- **bench basics** — develop a backup attacker and a setup basic while bench has space.
- **attach energy** — target the active attacker (or the next attacker), not a random bench.
- **attach tool** — target the active attacker that lacks a tool.
- **evolve** — evolve when the line is ready, unless an immediate attack/KO dominates.
- **search → hand** — fetch the *missing plan piece*; fetch a basic before an orphan evolution.
- **discard** — pay costs with excess energy first; never discard the *only* setup/attacker/payoff.
- **attack** — prefer attacking (or attach→attack) over a passive draw/search loop when ready.
- **avoid deckout** — penalize/decline optional draw/search as the deck thins.
- **prepare backup attacker / recover after KO** — promote the best attacker, develop a backup
  before optional draw when the active is near KO.
- **stop passive loops** — do not repeat draw/search when a board-advancing action exists.

## Layer 3 — Deck playbook (card roles + weights)

A YAML file per deck shell. Supplies what the generic layer cannot know:

- **role tags** — which card ids are `primary_basic_attacker`, `setup_basic`,
  `evolution_payoff`, `search_cards`, `high_risk_search`, `tools`, `draw_support`, `stadium`,
  `basic_energy`.
- **role weights / preferences** — active prefers attacker, bench prefers backup+setup, attach
  prefers active/next attacker, search prefers the missing plan piece, discard prefers excess
  energy, preserve-only rules for the last setup/attacker/payoff.
- **plan priorities** — primary/secondary plan and the avoid-plans (passive draw loop, deckout).
- **safe / unsafe discard definitions** and **deckout thresholds**.

This pass ships `playbooks/v2_kyogre_abomasnow_core_pilot.yaml` for the Water shell.

## Layer 4 — Card-specific exceptions (rare + explicit)

Only where mechanics + roles are insufficient. Each is a named, documented guard:

- **Secret Box guard** — avoid when there are too few safe discards and a productive
  alternative exists (play safety is *advisory*; forced discard-all is not a failure).
- **Ultra Ball discard/search** — discard excess energy to pay the cost; fetch the missing
  basic before an orphan evolution.
- **Mega Signal line guard** — do not commit the Mega line without its setup basic on board.
- **chaos cards** — deferred (the chaos lane stays closed; see `docs/CHAOS_PLAYBOOK_LANE.md`).

The proven Pass-8 effect-safety guards (discard-protect-setup, search-avoid-orphan,
deckout-decline) already implement several of these and are preserved beneath the core pilot.

---

## How the layers are compiled

The lab-side modules in `src/ptcg_activegraph/pilot/` are the source of truth for the generic
layer. The compiler (`pilot/compiler.py`) embeds their **stdlib-only** source plus the
playbook role maps (as Python literals) into a candidate `main.py` override block that wraps
the existing embedded agent. The candidate stays stdlib-only and never imports `src`.

Because the **fixtures grade the same `core_pilot_decide` the compiler embeds**, the
deterministic core-competency gate tests the decision logic that actually ships — there is no
divergence between "what we tested" and "what we submit".
