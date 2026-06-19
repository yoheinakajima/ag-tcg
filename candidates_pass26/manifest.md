# Pass 26 — Candidate Manifest (BLOCKED: no_build_no_trigger)

- decision: **no_build_no_trigger**
- any trigger-coverage passed: False
- candidates built: **none**
- tarballs: **none**
- No opportunity class cleared the Part-G trigger-coverage gate, so no runtime hook is justified by replay evidence. Building a candidate would mean shipping a guard that provably never fires (or fires only in broad-Main, which must stay delegated).

## Blocked candidates (would-have-been)

| candidate | intended hook | ctx | why blocked |
| --- | --- | --- | --- |
| `water_action_opportunity_guard_v1` | `discard_preserve_line_failure` | 8 | discard_preserve_line_failure has only 1 high-confidence + 1 medium loss window (< the 2-high-confidence-loss-window bar); the medium window discarded a Mega with no Snover line in play (uncastable), so preserving it would not have helped. |
| `water_action_opportunity_guard_v2` | `bench_backup_available_unplayed` | 0 | bench_backup_available_unplayed has 75 windows but lives in broad-Main (ctx0), which must stay delegated, and is already covered by the proven base hook `emergency_backup_bench`. Not narrow / not fixture-isolable as a NEW lever. |

No invented card ids. Root `main.py` / `deck.csv` untouched. No upload, no GitHub push (`no_upload=true`).
