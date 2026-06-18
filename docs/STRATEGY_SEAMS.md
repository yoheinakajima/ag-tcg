# Strategy seam taxonomy

This is the planning document and roadmap for the ActiveGraph strategy lab. A
**seam** is a place where the agent or deck can be varied to create a testable
experiment branch. The machine-readable companion is
[`experiments/strategy_seams.yaml`](../experiments/strategy_seams.yaml); the
hand-editable priorities live in
[`experiments/experiment_plan.yaml`](../experiments/experiment_plan.yaml).

The control we compare every candidate against is the immutable
**v1 Kaggle baseline** (`data/baselines/v1_kaggle_349_8/`, public score 349.8).

Each seam in the YAML declares: `id`, `family`, `description`,
`default_priority` (0–100, higher = tested earlier), `risk`, `requires`
(data/capabilities needed first), and `enabled` (may we generate candidates
now). A seam whose `requires` are not satisfied is reported as **blocked**
rather than guessed at.

---

## 1. Deck construction seams

How the 60-card list is built. Deck seams need card metadata
(`data/cards/EN_Card_Data.csv`) so we never invent card IDs and can check
legality (exactly 60 cards, ≤4 copies of any non-basic-energy card, basic
energy unlimited).

- **energy count** — trim excess basic energy for consistency cards.
- **basic Pokémon count** — enough basics to avoid dead opening hands.
- **attacker package** — which attackers and how many.
- **evolution package** — evolution lines and their support.
- **draw/search density** — supporters/items that dig for resources.
- **supporter/item/stadium mix** — trainer ratio balance.
- **trainer complexity** — keep choices bot-playable.
- **type/color consistency** — single dominant energy type.
- **prize liability** — how many prizes each KO concedes.
- **recovery cards** — recycle/heal for long games.
- **disruption cards** — hand/energy/board disruption.
- **bench pressure cards** — spread/bench-targeting threats.
- **retreat/switch cards** — mobility and pivoting.
- **anti-baseline techs** — cards aimed at the mirror.
- **bot-playability / branching complexity** — fewer fragile decision points.

## 2. Policy seams

How `main.py` ranks the legal options the engine presents. These are the
**safest** seams: they edit scoring constants only, require no card metadata,
and keep `main.py` standard-library-only and self-contained.

- **attack priority** — weight of confirmed attack option (type 13).
- **energy attachment priority** — attach/energy preference.
- **evolution priority** — evolve/evolution preference.
- **benching rules** — placement (type 8) preference.
- **active promotion after KO** — promotion choices.
- **retreat/switch rules** — when to pivot.
- **card search target selection** — what to fetch.
- **draw/search sequencing** — order of resource plays.
- **supporter timing** — when to spend the supporter.
- **item timing** — when to spend items.
- **pass/end avoidance** — penalty on pass/end (type 14).
- **multi-select behavior** — handling `maxCount > 1`.
- **target selection** — which target among legal ones.
- **hidden-information assumptions** — conservative defaults.
- **fallback behavior** — guaranteed-legal last resort.

### 2a. Replay-derived effect-resolution policy seams (Pass 4)

These seams came out of studying the Kaggle scored game (episode `80374966`).
The earlier policy seams are about *which option type* to take; these are about
**effect-resolution card choice** — when a card (Ultra Ball, Secret Box, Mega
Signal) forces a search/discard sub-prompt, *which card* should be fetched or
discarded. The only override hook in `main.py` is keyword / option-type
weighting (there is **no board-state card-targeting hook**), so every candidate
built from these seams is an honest **lightweight keyword-weight approximation**
that biases the ranker toward high-value card *names* (which appear in the
serialized option text) — not a true rule engine. Each is gated on
`official_card_csv` so it can only reference confirmed card ids.

- **effect-resolution targeting** (`policy.effect_resolution_targeting`, prio 95)
  — on search/to-hand prompts prefer high-value targets by role over first-legal
  or basic energy.
- **Ultra Ball discard & search** (`policy.ultra_ball_discard_and_search`, 92) —
  Ultra Ball (1121): discard the lowest-value card, search the highest-priority
  missing board piece. Only the search-target side is keyword-expressible.
- **Secret Box mode selection** (`policy.secret_box_mode_selection`, 88) — Secret
  Box (1092): pick the high-leverage item/supporter/tool/stadium bundle.
- **Mega Signal evolution search** (`policy.mega_signal_evolution_search`, 86) —
  Mega Signal (1145): fetch the Mega Abomasnow line only when Snover is in play.
- **attach targeting** (`policy.attach_targeting`, 84) — attach energy/tools to
  the active / next-turn attacker rather than the first legal target.
- **setup active choice** (`policy.setup_active_choice`, 80) — choose the opening
  Active (Kyogre vs Snover) by race-vs-evolve matchup intent.
- **deckout awareness** (`policy.deckout_awareness`, 70) — avoid unnecessary
  draw/search when the deck count is low, to dodge self-deckout.

Of these, the keyword-expressible ones are generated this pass
(`effect_resolution_targeting`, `ultra_ball_discard_and_search`,
`secret_box_mode_selection`, `attach_targeting`). The remaining three
(`mega_signal_evolution_search`, `setup_active_choice`, `deckout_awareness`)
require board state the override hook cannot see, so they are documented but not
generated as candidates yet.

**Pass 5 update.** Pass 4's keyword weights were largely inert: the option
scorer only sees `{area, index, type}` — the card *identity* is not in the
option text, it lives in `select.deck[index].id` / `hand[index].id`. So name
weights almost never bit; only option-*type* weights did. Pass 5 therefore
injects a genuinely **board-aware** override scorer into each candidate that
resolves the card id behind each option (via `area`/`index`), reads own
`deckCount` and `active`/`bench`, and adds a score delta accordingly (fully
`try/except`-guarded so it can never raise). This lets the previously-blocked
board-dependent seams (`mega_signal_evolution_search`, `setup_active_choice`,
`deckout_awareness`, plus a `combo.effect_resolution_deckout` pairing) be
generated as real candidates this pass over the v2 deck — no invented card ids,
all referencing confirmed ids only.

## 3. Strategy archetype seams

Named bundles of policy (and later deck) choices forming a coherent gameplan.

- **linear aggro** — attack-first, minimal branching.
- **consistency engine** — value steady card flow.
- **big basic / ex beatdown** — few large attackers.
- **setup evolution deck** — build evolution + energy first.
- **single-prize prize-trade deck** — favourable prize math.
- **disruption-lite** — light disruption tilt.
- **baseline/mirror exploit** — the v1 control as the diversity anchor.
- **anti-meta counterdeck** — counter the expected field.
- **time-pressure/simple-turn deck** — fast, low-decision turns.
- **higher-ceiling research deck** — speculative, higher variance.

### 3a. Human-directed chaos archetype seams (Pass 4, blocked)

Chaos decks are asymmetric **disruption** decks (not random play): they create
unstable hand / bench / deck / status states that a simple bot mis-handles, so
our straightforward policy can exploit the resulting mistakes. Every core card
id below is **confirmed** against `data/cards/EN_Card_Data.csv` (see
`data/cards/pass4_id_confirmation.json`). They all stay **blocked**
(`enabled: false`, gated on `chaos_decklist_confirmed`) because a legal 60-card
list cannot be assembled from the ~8–10 confirmed cores without inventing the
remaining ~50 ids — which this pass forbids.

- **hand avalanche** (`chaos.hand_avalanche_froslass`, prio 58) — preserve large
  opponent hands, then convert hand size to damage with Mega Froslass ex.
- **bench bloat punisher** (`chaos.bench_bloat_punisher`, 56) — crowd the
  opponent bench with Accompanying Flute, punish with bench-scaling attackers.
- **mill / resource destruction** (`chaos.mill_resource_destruction`, 54) —
  disrupt deck/hand/energy so brittle bots lose pieces or deck out.
- **status confusion lock** (`chaos.status_confusion_lock`, 52) — Confusion /
  Burn / Sleep plus forced switching to cause mis-sequencing and lost turns.
- **Vivillon/Decidueye four-card lock**
  (`chaos.vivillon_decidueye_four_card_lock`, 50) — use Vivillon/Judge to set the
  opponent to exactly 4 cards, enabling Decidueye ex's reduced-cost attack.

When a future pass confirms a full, legal chaos decklist, flip `enabled: true`
and the generator will start producing those candidates automatically.

## 4. Evaluation seams

How candidates are measured locally with cabt before any upload.

- **self-play vs baseline** — candidate vs immutable control.
- **first-player vs second-player split** — seat fairness.
- **seed sweep** — many games, not one lucky result.
- **mirror match** — candidate vs itself.
- **generated deck matrix** — cross-play of deck variants.
- **timeout rate** — hard gate on hangs.
- **validation safety** — package verify + smoke must pass.
- **decision entropy** — how varied the decisions are.
- **first meaningful attack turn** — tempo proxy.
- **prize curve** — prize progression over the game.
- **fallback count** — how often the safe fallback fired.
- **pass/end rate** — how often a pass-like option was taken.
- **attack rate** — how often an attack was taken.
- **game length** — average/maximum steps.
- **local win rate** — wins vs the control.
- **Kaggle rating delta** — change vs 349.8 once uploaded.

### 4a. Pass 5 chaos / deckout telemetry (now available)

Earlier passes treated local games as a black box that only emitted a
win/loss reward, so chaos / deckout hypotheses had **no telemetry** to test
against. Pass 5 lifts that blocker: the local evaluation harness
(`experiments/runner.py`) now instruments every candidate decision and records
a per-game `telemetry` block alongside the existing win/attack/pass stats.

What is now captured (per game, candidate seat only):

- **`min_deck_count` / `deck_count_last`** — the lowest own deck size seen and
  the final own deck size, the core signal for deckout proximity.
- **`low_deck_decisions`** — count of decisions taken at or below the deckout
  threshold (≤ 6 cards), i.e. how often the agent acted while near deckout.
- **`search_decisions` / `discard_decisions`** — effect-resolution prompts by
  `select.context` (search-to-hand = 7, discard = 8), the contexts where the
  replay's mis-resolutions occurred.
- **`max_bench_seen` / `max_hand_seen`** — own bench and hand high-water marks,
  the board-pressure signals chaos archetypes care about.
- **`context_counts`** — raw histogram of every `select.context` value seen.

### 4b. Pass 6 correction — opponent counts/board/status ARE observable

Pass 5's "all opponent state is hidden" assumption was **too conservative**.
Verified against replay `80374966` (`observation.current.players[i]`), our seat
observes, for **both** seats: `handCount`, `deckCount`, `active`/`bench` revealed
card ids, `benchMax`, `discard`, `prize` count, and the status flags
(`asleep`/`burned`/`confused`/`paralyzed`/`poisoned`). What stays genuinely
hidden for the opponent is only the **contents** of face-down zones: `hand`
(null while `handCount` is a real integer), `deck` (absent from the observation —
only `deckCount`), and `prize` identities (null placeholders; count observable).

`src/ptcg_activegraph/experiments/telemetry.py` `read_observation()` returns this
corrected view with explicit `uncertainty` flags for every null / face-down
entry. Consequently each chaos seam's **policy trigger** (opponent hand size,
bench size, deck count, status flags) is observable and can drive a candidate.
Two caveats remain, recorded honestly per seam in
`data/experiments/chaos_telemetry_contract.json`:

1. **Payoff proof is a proxy.** The harness records win/loss + decision
   telemetry, not per-attack damage dealt, so "big hand → big damage" causation
   stays a win-rate proxy, not a proven mechanism.
2. **Build gate.** A legal 60-card decklist must still be confirmed from MATCHed
   card ids (never invented) and pass smoke before a seam is evaluated; where
   that is not met the seam stays blocked with the exact reason.

**Limitations (honest scope).** Telemetry is still derived from the cabt
observation only; opponent hand/deck/prize *contents* and any face-down identity
remain `uncertain`. The override layer's hooks are option-type / keyword /
board-state weights, not a full targeting engine; the telemetry measures
outcomes and observable triggers, it does not simulate hidden information.

## 5. Reporting seams

What the markdown/HTML report exposes for full transparency.

- **hypothesis** — what we expected and why.
- **branch lineage** — idea → hypothesis → branch → result.
- **deck diff** — composition change vs control.
- **policy diff** — scoring-constant change vs control.
- **local metrics** — the evaluation numbers.
- **failures/regimes** — what broke and how it was tagged.
- **promotion/rejection decision** — why a candidate moved on or not.
- **Kaggle score after upload** — realized result.
- **lessons learned** — carried into the next batch.

---

## Blocked seams (this pass)

These are intentionally `enabled: false` until their `requires` are confirmed
from card metadata, so we never invent card identities or strategies:

- `deck.abomasnow_line_focus` — needs Snover / Mega Abomasnow ex IDs confirmed.
- `deck.anti_baseline`, `archetype.toolbox` — need identified counters/attackers.
- `deck.prize_liability`, `deck.recovery_package` — need prize/recovery tags.
- `archetype.disruption_lite` — needs disruption cards/options identified.

When a future pass confirms the relevant card IDs, flip `enabled: true` and the
generator will start producing those candidates automatically.
