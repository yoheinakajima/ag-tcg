# Local Simulation

How to run matches locally with `cabt` + `kaggle-environments`, and how the
system behaves when they are absent.

## Setup

```bash
pip install kaggle-environments
pip install cabt    # from the competition's provided wheel / source
```

`cabt` is the competition simulator built for `kaggle-environments`. It is not on
PyPI in general; install it from the package the competition provides.

Useful cabt APIs the lab targets:

```
all_card_data()  all_attack()  visualize_data()
search_begin(...)  search_step(search_id, select)  search_end()  search_release(search_id)
battle_start(deck0, deck1)  battle_select(select_list)  battle_finish()
```

## Capability check

Everything is gated behind `sim/cabt_adapter.py`:

```python
from ptcg_activegraph.sim import is_available
is_available()        # True only if cabt (and ideally kaggle-environments) import
```

When unavailable, simulation methods raise `CabtUnavailableError` with an
actionable install hint, and the CLI scripts print that hint and exit cleanly.

## Self-play

```bash
python scripts/run_self_play.py --games 50 --deck deck.csv \
    --out data/matches/events.jsonl --render data/reports/replay.html
# Exits with install instructions (code 1) if cabt is missing.
# Use --allow-missing to exit 0 in CI.
```

This runs the runtime `agent` against itself via `LocalRunner`, which emits
ActiveGraph events (`MatchStarted`, `DeckLoaded`, `GameEnded`, ...) into the
event store. Those feed projections and the report generator.

## Tournament

```bash
python scripts/run_tournament.py --deck deck.csv --games 2
```

`sim/tournament.py:round_robin` plays every pair of `(agent, deck)` entrants. The
default entrants are the heuristic agent vs. a fallback baseline. Without cabt it
prints the **planned schedule** and exits.

## Replay saving

`sim/replay_io.py` saves/loads replay JSON; `CabtAdapter._try_render` writes
`visualize_data()` output to an HTML path when `--render` is given.

## Wiring the real battle loop

`CabtAdapter.run_game` is a guarded skeleton. Once cabt is installed, finalize:

1. `battle_start(deck0, deck1)`.
2. Loop: read the observation, call the agent, pass its selection to
   `battle_select(...)` until the game ends.
3. `battle_finish()` → outcome; translate to `{winner, result, turns}`.

Validate the exact observation/return shapes against the installed build, then
remove the placeholder comments. The `LocalRunner` event emission around it does
not need to change.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| "cabt unavailable" | `cabt`/`kaggle-environments` not installed — see Setup. |
| Self-play exits code 1 | Expected without cabt; add `--allow-missing` for CI. |
| Empty report metrics | No events yet — run self-play first. |
| Deck won't load | Ensure 60 integer IDs; see `docs/KAGGLE_SUBMISSION.md`. |
