# First Kaggle Submission Checklist

Catch likely errors **before** uploading. Work top to bottom.

```
[ ] Official Kaggle competition rules accepted
[ ] Official data downloaded / mounted
      - data/cards/EN_Card_Data.csv  (and/or JP_Card_Data.csv)
      - sample_submission/deck.csv   (if provided)
[ ] deck.csv resolved from sample / provided / generated source
      python scripts/resolve_deck.py        # must print source != "placeholder"
[ ] unit tests pass
      python -m pytest
[ ] submission preflight passes
      python scripts/package_submission.py --verify-only
[ ] cabt smoke test passes in a Kaggle-like env
      python scripts/kaggle_smoke_test.py    # prints PASS
[ ] tarball is clean
      tar -tzf data/submissions/submission.tar.gz   # ONLY top-level main.py + deck.csv
[ ] main.py is standard-library only (no src/, no third-party imports)
[ ] deck.csv is NOT a placeholder (deck.meta.json source != "placeholder")
[ ] no external network calls in runtime
[ ] no heavyweight imports in runtime
[ ] no live LLM calls in runtime
[ ] fallback agent works with malformed observations (covered by tests)
[ ] self-play validation succeeds locally (smoke test)
```

## Why each matters

* **Valid deck** — a placeholder or non-60 deck fails Kaggle validation and
  scores nothing. The resolver + packager block placeholders by default.
* **Valid return shape** — `agent(obs)` must return `list[int]`; the packager
  imports `main.py` and asserts this on empty/None/null-select inputs.
* **No crashes / timeouts** — `main.py` never raises outward and does no search
  by default, so it stays well within per-step limits.

## When the smoke test fails

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `FAIL: agent import error` | `main.py` imports something unavailable | keep `main.py` stdlib-only; don't import `src/` |
| `FAIL: cabt environment unavailable` | `cabt` not installed or wrong `make()` config | install cabt; check `make("cabt", configuration=...)` |
| `FAIL: deck invalid` | deck not 60 ints / placeholder | `python scripts/resolve_deck.py` |
| `FAIL: runtime exception` | bug hit during a real game | read the printed traceback; reproduce with `scripts/explain_action.py` |
| Timeout | per-step work too heavy | keep search disabled; ensure no I/O in `agent` |
| Hidden schema mismatch | option schema differs from assumptions | `python scripts/record_schema.py`; inspect `docs/CABT_SCHEMA_NOTES.md` |
| Package nesting issue | files under a subdir in the tarball | rebuild with `scripts/package_submission.py` (inspects + rejects nesting) |

## Final command sequence

```bash
python -m pytest \
 && python scripts/resolve_deck.py \
 && python scripts/package_submission.py --verify-only \
 && python scripts/kaggle_smoke_test.py \
 && python scripts/package_submission.py \
 && tar -tzf data/submissions/submission.tar.gz
```

If every step is green and the tarball lists exactly `main.py` and `deck.csv`,
you are ready to upload `data/submissions/submission.tar.gz`.
