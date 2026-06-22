---
name: shared-artifact stale snapshot tests across passes
description: why older-pass tests reliably go red after a newer pass runs, and which failures are pre-existing vs real
---

The ActiveGraph PTCG repo keeps a handful of SINGLE shared mutable artifacts that
every pass overwrites in place:
- `data/submission_queue.json`
- `docs/PTCG_STRATEGY_CANVAS.md`
- `data/site/index.html`
- `data/reports/activegraph_strategy_report.md`
- `experiments/meta_pool.yaml` + the live registry (active_control)

Each pass's Part M/K writes its own snapshot into these files, and many older passes
shipped STRICT snapshot tests against them (exact active_control id, exact queue
emptiness, "site/canvas/report carry passN decision tuple", exact disclaimer string).

**Consequence:** as soon as a later pass overwrites a shared artifact, older strict
tests against it go red — this is structural, not a regression. Two flavors recur:
meta/registry tests (exact active_control id, meta_pool weights) and report/queue
snapshot tests (exact disclaimer strings, "carry passN decision tuple", exact queue
emptiness).

**Why:** the repo intentionally uses one living canvas/site/report/queue, owned by the
LATEST pass. Some passes wrote forward-compatible loose tests (e.g. queue `len<=1`);
others wrote STRICT exact-state tests (e.g. `len(queue)==0`) that any later queueing
pass necessarily breaks.

**How to apply:**
- When a new pass legitimately queues a candidate, expect the prior pass's
  `submission_queue_empty` test to flip red. That is correct, not a bug to hide.
- Prefer writing your OWN pass's queue/report tests forward-compatibly (`<= 1`,
  substring caveat checks) so the next pass doesn't inherit a red.
- Do NOT rewrite an older pass's historical finding to make it green — it documents
  that pass's true point-in-time state. Just report the expected staleness.
- To tell pre-existing from self-inflicted: `git show HEAD:<shared file>` and check
  which pass's content it holds; tests for older passes than that were red before you.

**Forward-compat applies only to SHARED artifacts; PASS-SPECIFIC ones are safe to strict-pin.**
The "write loose/forward-compatible tests" rule is about the shared mutable files above. A
pass's OWN `pass<NN>_*.json` evidence (e.g. `pass46k_edge_analysis.json`,
`pass46k_strategy_decision.json`) is NOT shared — a later pass writes `pass<NN+1>_*.json` and
never overwrites it. So a STRICT snapshot pinning *this* pass's exact rationale (e.g. "inconclusive
SPECIFICALLY because triggered `spec_vs_spec` noise is dirty while practical/attribution/Fisher/
min-gating are all green") is correct and durable, not brittle. Architect review will actively ask
for such a snapshot to stop the decision->gate-state map from passing under the *wrong* reason.
Keep BOTH: a forward-compatible generic ladder/map test (re-derives) AND a pass-specific snapshot
test (pins the actual point-in-time evidence).

**Site caveat — do NOT regenerate the shared site in a gameplay pass.**
`scripts/build_report_site.py` (generic `write_site`) rebuilds `data/site/index.html`
from events/runs ONLY and does NOT carry the accumulated per-pass narrative blocks +
"NOT A KAGGLE LEADERBOARD" `<p class="caveat">` paragraphs that the committed
index.html holds (that narrative is frozen at Pass 40; gameplay passes 41+ leave the
site untouched). Running it in a non-reporting pass therefore STRIPS those disclaimers
and breaks `test_pass17/18 *_carry_not_a_kaggle_leaderboard_disclaimer` — a REAL
self-inflicted regression, distinct from the benign staleness above (confirmed by
`git show HEAD:data/site/index.html | grep -c 'NOT A KAGGLE LEADERBOARD'` = 4 vs 0
after regen). For a LOCAL-ONLY gameplay pass, do NOT run build_report_site.py; leave
`data/site/*` as-is. The emitter only needs the site PATH to exist, and pass-specific
tests (e.g. test_pass46g) don't read site content — so reverting the site to HEAD
costs nothing and restores the disclaimers.
