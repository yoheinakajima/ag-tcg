# data/cards/

Drop the official card metadata CSVs here:

* `EN_Card_Data.csv`
* `JP_Card_Data.csv`

The loader (`ptcg_activegraph.cards.load_card_db`) is schema-tolerant: it
normalizes a `card_id` and `name` from common column names and keeps all original
columns. After adding a CSV, run:

```bash
make inspect-cards
```

These files are git-ignored; this README and `.gitkeep` keep the directory.
