# Playbooks

Declarative, deck-specific **playbooks** for the Pokémon TCG AI Battle repo
(ActiveGraph Pass 9). A playbook makes a deck's strategy explicit and
reportable, and is compiled into a stdlib-only candidate `main.py`.

## Why playbooks?

Pass 8 established two principles:

1. **Fixture gate beats raw win rate.** A candidate that wins locally but fails
   the replay-derived hard fixtures is not uploadable.
2. **Deck-specific pilots are required.** A single generic Pokémon policy cannot
   encode line-coherence (e.g. don't fetch an orphan Mega Abomasnow ex with no
   Snover). Effect-resolution targeting is deck-specific.

A playbook captures that deck-specific intent declaratively, so strategy is
visible, reviewable, and iterable — not buried in heuristics.

## Files

- `v2_kyogre_abomasnow.yaml` — the active v2 control deck pilot (Kyogre pressure
  + Snover → Mega Abomasnow ex setup). Compiles to the full effect-safety guard
  set (equivalent to `combo_full_safety_v3`).
- `chaos_hand_avalanche_froslass.yaml` — documentation-only chaos skeleton
  (blocked / not-ready).
- `chaos_bench_bloat_punisher.yaml` — documentation-only chaos skeleton
  (blocked / not-ready).

## Schema (top-level fields)

`deck_id`, `baseline_id`, `cards`, `roles`, `gameplan`, `opening`,
`main_phase_priorities`, `effect_resolution`, `discard_safety`, `search`,
`deckout_guard`, `attachment`, `fixture_requirements`, `report_notes`.

Card ids must be **confirmed** in `data/cards/EN_Card_Data.csv`. Inventing an id
is a hard validation failure.

## Compiled effect-safety rules

The compiler (`src/ptcg_activegraph/playbooks/compiler.py`) derives the proven
Pass-8 guards from the rule sections:

| rule | playbook source |
| --- | --- |
| `discard_protect_setup` | `discard_safety.protect_setup` |
| `search_avoid_orphan_evolution` | `search.avoid_orphan_evolution` |
| `search_avoid_orphan_mega_signal` | `search.avoid_orphan_mega_signal` |
| `decline_mega_signal_no_snover` | `effect_resolution.decline_mega_signal_no_snover` |
| `deckout_decline_threshold` | `deckout_guard.decline_threshold` |

The generated `main.py` is the root agent with the rendered guard block injected:
self-contained, standard-library only, returns the deck on `select=None`,
validates/clamps indices, and never raises outward. It imports no `src` module.

## Usage

```bash
python scripts/validate_playbook.py playbooks/v2_kyogre_abomasnow.yaml
python scripts/compile_playbook.py playbooks/v2_kyogre_abomasnow.yaml \
    --candidate-id playbook_v2_kyogre_abomasnow_v1
python scripts/generate_playbook_candidate.py --group pass9_playbooks
```

This is a **local research** surface: no Kaggle upload, no GitHub push, and the
root `main.py` / `deck.csv` are never modified.
