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

## Replay inbox now supplies this telemetry (Pass 11B)

The replay inbox (`docs/REPLAY_WORKFLOW.md`) gives us the raw opponent-side
telemetry needed to *measure* chaos for the first time. From the parsed replays we
can read:

- opponent `handCount`
- opponent `deckCount`
- opponent bench count
- status flags
- discard events
- forced active/bench movement **if it is logged in the replay**

That closes the *measurement* gap, but it does **not** open the chaos gate. Chaos
is still **not upload-ready** until **all** of the following hold:

1. payoff cards are confirmed (a real win condition, with confirmed card ids),
2. the chaos trigger is **measurable** from the telemetry above,
3. the cabt evaluation includes **replay-derived archetypes** as opponents, and
4. the chaos candidate is shown to **not help the opponent set up**.

As of Pass 11B the cabt eval *does* include replay-derived archetypes
(`scripts/run_meta_pool_eval.py`), but those results are **surrogate-based and
directional only**, the dominant opponent family is still **provisional**, and no
payoff card / measurable trigger is confirmed — so conditions 1, 2, and 4 remain
unmet and the gate stays **closed**.

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

## Chaos after meta decomposition (Pass 13)

The Pass 13 decomposition split the previously-dominant `unknown_ex_tempo` bucket
into four **replay-grounded opponent subfamilies**
(`mega_lucario_ex_tempo`, `mega_kangaskhan_energy_stack`, `dragapult_ex`,
`lightning_bellibolt`; see
`data/meta_replays/unknown_ex_tempo_decomposition.json`). This changes the chaos
picture in one important way: **chaos is more plausible once opponent subfamilies
are known**, because a disruption line can now be aimed at a *specific* opponent
weakness instead of a vague "ex tempo" blob.

It does **not** open the gate. The hard rules above still hold, and chaos must be
built as **separate playbook families** — not as a few disruption cards sprinkled
into the Water deck. Mixing chaos cards into an existing archetype dilutes both
plans and was a past failure mode.

**Every chaos candidate still requires all five of:**

1. a **disruption card** (confirmed card id),
2. a **payoff card** / win condition (confirmed card id),
3. a **measurable trigger** readable from replay/cabt telemetry,
4. a **safety guard** (fire only when measurably advantageous; never help the
   opponent set up), and
5. a **replay/meta target** (which subfamily it is meant to beat).

**Potential target mappings (hypotheses only — not built):**

| Chaos lever | Target signal | Candidate opponent subfamily |
| --- | --- | --- |
| hand-size punishment | draw-heavy hand refills | draw-heavy ex tempo decks |
| bench-bloat punishment | overbenching / wide setups | `mega_kangaskhan_energy_stack`, `mega_lucario_ex_tempo` |
| mill / resource pressure | deck-thinning / heavy search | decks leaning on `Buddy-Buddy Poffin` / `Ultra Ball` engines |
| status / forced-switch | single-attacker ex reliance | `dragapult_ex`, `lightning_bellibolt` (ex tempo) |
| discard / recovery traps | discard-pile recursion dependence | any subfamily shown to recur from discard |

These mappings are **directional hypotheses derived from surrogate decks**, not
confirmed opponent behavior. A surrogate deck approximates the *cards*, not the
*policy*, so each mapping must be validated against real replay telemetry before a
candidate is built.

**Do not build chaos candidates yet.** The next prerequisite is to instrument the
disruption telemetry (§ Required telemetry) against the refined subfamilies and
confirm a payoff card + measurable trigger for at least one mapping. Until then
the gate stays **closed**.
