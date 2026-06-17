# data/

Working data for the ActiveGraph lab. Most contents are **generated artifacts**
and are git-ignored (see `.gitignore`); the directories are kept via `.gitkeep`.

| Dir | Contents | Tracked? |
| --- | --- | --- |
| `cards/` | Official card CSVs (`EN_Card_Data.csv`, `JP_Card_Data.csv`) | drop-in, ignored |
| `decks/` | Saved/experimental decklists | ignored |
| `matches/` | `events.jsonl` ActiveGraph event log + replays | ignored |
| `reports/` | Generated Strategy reports, replay HTML | ignored |
| `submissions/` | Built `submission.tar.gz` bundles | ignored |

## Getting card data

Place the competition's card CSVs under `data/cards/`:

```
data/cards/EN_Card_Data.csv
data/cards/JP_Card_Data.csv
```

Then `make inspect-cards` to confirm ingestion and role tagging. If you instead
have `cabt` installed, the card DB can load from `all_card_data()` automatically.

## Event log

`data/matches/events.jsonl` is the append-only source of truth for the lab. It is
created on first write by `EventStore`. Safe to delete to reset the lab; it will
be recreated.
