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
