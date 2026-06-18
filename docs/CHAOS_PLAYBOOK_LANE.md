# Chaos Playbook Lane (research lane — NOT a candidate queue)

**Status: research/preparation only.** No chaos candidate is generated, queued,
validated for upload, or submitted by this document or this pass. This file keeps
the chaos disruption idea alive as a *future* research lane and records the exact
preconditions that must be met before any chaos candidate may even be built.

## Why chaos may exploit simple agents

Simple/greedy opponents tend to assume an uninterrupted board and hand. Chaos
lines attack those assumptions:

- **Forced switching** — drag up a benched/unready Pokémon, denying the opponent
  their attacker tempo.
- **Discard pressure** — strip resources from hand/board faster than they can
  rebuild.
- **Hand disruption** — shuffle/discard the opponent's hand so their scripted
  sequencing breaks.
- **Deckout / mill** — win by emptying the opponent's deck instead of taking
  prizes.
- **Status conditions** — sleep/confusion/paralysis to skip or randomize their
  attacks.
- **Bench bloat** — bait the opponent into overcommitting the bench, then punish.
- **Trash / recovery manipulation** — deny or exploit discard-pile recovery.

## Why chaos is dangerous (why we are NOT shipping it yet)

- Disruption can **help the opponent set up** (e.g. forcing a switch into a
  better attacker, or giving them draw).
- It **needs a payoff card / win condition** — disruption without a closer just
  slows the game and loses on prizes.
- It needs **strict playbook triggers** — fire only when the disruption is
  measurably advantageous, not on sight.
- It needs **metrics/telemetry** to know whether disruption actually worked.

## Required telemetry (must exist before any chaos candidate)

- opponent `handCount`
- opponent `deckCount`
- opponent bench count
- status flags (sleep/confusion/paralysis/poison/burn)
- discard contents (opponent + self)
- forced-switch logs (who was forced, into what)
- missed-attack / pass-after-disruption events

## Candidate families to revisit (later, gated)

- `hand_avalanche_froslass`
- `bench_bloat_punisher`
- `mill_resource_destruction`
- `status_confusion_lock`
- `discard_recovery_trap`

## Hard rule

> **No chaos candidate may be queued unless its payoff trigger is *measurable*
> and a working cabt/replay evaluation exists to test it.**

As of Pass 10B cabt evaluation is available again, but the disruption telemetry
above is **not yet instrumented**, so the gate remains **closed**. Chaos work
stays in this research lane until the telemetry exists and a payoff trigger is
defined and measurable.
