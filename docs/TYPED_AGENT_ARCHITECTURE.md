# Typed Board-Aware Agent Architecture (Pass 35)

> LOCAL ONLY. Internal/surrogate evidence; NOT the Kaggle leaderboard. No upload,
> no submit, no GitHub push. No invented card IDs. The official card CSV and raw
> replay JSON are never shipped in candidate tarballs nor committed.

## 1. Why this exists

External analysis of the Kaggle sample agents found that strong agents **decode the
typed cabt state and reason over the board**, while our compiled agents mostly score
opaque options with a few narrow context hooks. Pass 35 adds a typed, board-aware
strategy layer that reads the board, evaluates legal options with card/state context,
and produces deck-specific decisions — without copying competitor code or decklists.

## 2. Lane decision — stdlib typed-lite (Option B)

The Kaggle examples import `cg.api` (`to_observation_class`, `all_card_data`,
`get_card`, typed `SelectContext`/`OptionType`). **`cg` exists only inside the
installed `kaggle_environments` package — it is not a repo-shippable library.**

Our candidate tarball contract is strict and AST-enforced
(`scripts/validate_candidate_entrypoint.py`):

- exactly two top-level files: `main.py` + `deck.csv`;
- standard-library imports only;
- the runtime must not import `src.ptcg_activegraph`.

Bundling `cg` would break that contract and require a parallel packaging/validator
lane that this pass does not justify. The same typed signal the examples consume
(`select.context` ints, `option.type`, board HP/energy/tools, prize/deck counts) is
**reconstructable directly from the raw `obs_dict`**. Therefore Pass 35 uses a
**stdlib typed-lite** decoder, compiled (inlined) into candidate `main.py` using the
proven embed-not-import model.

## 3. Observation schema (what candidate runtime actually sees)

Audited from real observations (`data/experiments/pass35_typed_obs_audit.json`):

```
obs = { "logs": [...], "current": {...} | None, "select": {...} | None }

current: energyAttached, firstPlayer, looking, lookingCount, players[2], result,
         retreated, stadium, stadiumPlayed, supporterPlayed, turn,
         turnActionCount, yourIndex
players[i]: active[1], bench[], hand[], discard[], prize[],
            deckCount, handCount, benchMax,
            asleep, burned, confused, paralyzed, poisoned
pokemon (active/bench entry): id, hp, maxHp, energies, energyCards, tools,
            preEvolution, appearThisTurn, serial   (name MAY appear, not relied on)
card (hand/discard entry): id, serial, playerIndex   (numeric id only)
select: context, type, option[], minCount, maxCount, contextCard, deck, effect,
            remainDamageCounter, remainEnergyCost
option: type, area, index, playerIndex, inPlayArea, inPlayIndex, attackId, number
```

`prize` is a list — `len()` = prizes remaining. Card metadata (name/type/stage/
weakness/retreat/ex-mega) is **not** in the observation: cards appear as a numeric
`id`. Metadata must come from a compile-time table.

## 4. Honesty boundaries (unsupported by the option schema)

- **Attack damage / lethal / KO targeting** — attack options carry a *numeric*
  `attackId` only (no name, base damage, or effect text). Damage cannot be honestly
  estimated, so KO/lethal logic is **unsupported**.
- **Spread / Phantom-Dive / Boss / gust targets** — target identity is not exposed;
  never claim spread targeting (Pass-28 honesty rule).
- **Opponent hand identity** — hidden (`handCount` only); never assume identities.

These mechanics are marked `unsupported` in every StrategyProfile and are never
implemented as fake fixes.

## 5. Module design — `src/ptcg_activegraph/pilot_typed/`

Lab source of truth (stdlib-only so it can be inlined into candidates):

- `board.py` — safe extraction of the typed board view from `obs_dict` (self/
  opponent active/bench/hand/discard, prize/deck counts, stadium, status flags,
  per-Pokemon HP/energy/tools). Pure, never raises.
- `metadata.py` — lookup helpers over an inlined per-card metadata dict
  (`name`, `card_type`, `energy_type`, `stage`, `is_basic`, `ex`, `retreat_cost`).
- `tactics.py` — generic deterministic primitives: `get_card_from_option`,
  `prize_value`, `pokemon_target_score`, `safe_draw_count` (deckout guard),
  `choose_setup_active/bench`, `choose_search_target`, `choose_discard`,
  `choose_attach_target`, `choose_evolution`. KO/lethal/Boss helpers return an
  explicit "unsupported" sentinel rather than a guessed value.
- `profiles.py` — validation/access for a deck StrategyProfile literal.
- `decisions.py` — per-context decision routing (`decide(kind, board, options,
  profile)`), used both by fixtures and by the compiled runtime.
- `compiler.py` — emits a PASS35 typed override block appended to a base
  `main.py`: runs the proven base policy first, then refines **only** at
  reliably-identifiable contexts (0 main, 1 setup-active, 2 setup-bench,
  7 ToHand-search, 8 discard, 38 draw-count), keeping the base policy's
  action *count/type* and **bailing back to base on any error or mismatch**.

## 6. Runtime safety contract

- Pure, deterministic; ties broken deterministically.
- Never raises outward in compiled runtime — always falls back to the known-safe
  base policy when data is missing.
- Never selects illegal option counts (respects `minCount`/`maxCount`).
- No network, no LLM, no raw official CSV at runtime.
- Candidate runtime is stdlib-only and never imports `src.ptcg_activegraph`
  (the lab source is inlined at compile time).

## 7. Metadata provenance

A build step reads `data/cards/EN_Card_Data.csv` **locally** and emits a minimal
metadata dict for **only** the card ids used by our profiles and candidate decks.
That dict is inlined into candidate `main.py`. The CSV itself is gitignored and is
never shipped or committed (`data/experiments/pass35_card_metadata.json` records the
derived table for audit, keyed by our own ids only).
