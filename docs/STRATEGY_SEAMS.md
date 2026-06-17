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
