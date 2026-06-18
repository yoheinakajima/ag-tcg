---
name: Submission-queue artifact test leak
description: Tests exercising the queue builder must redirect QUEUE_JSON + CANDIDATES_DIR or they clobber the real artifact.
---

`queue.build_queue` (and its wrappers `pass6_pipeline.build_dry_run_queue` and
`dry_run_queue.build_dry_run_queue`) write to module-level default paths
`queue.QUEUE_JSON` = `data/submission_queue.json` and `queue.CANDIDATES_DIR` =
`data/submissions/candidates`. A test that calls any of these WITHOUT
redirecting those paths overwrites the real on-disk queue artifact with its
fixture data (symptom seen: the live queue silently became a `cand_a` fixture
with no `schema` key after running the full suite).

**Why:** the builder defaults to the real artifact location; pytest shares the
working tree, so a non-hermetic test mutates real data.

**How to apply:** any test touching the queue builder must
`monkeypatch.setattr(queue_mod, "QUEUE_JSON", tmp_path/"queue.json")` and
`...CANDIDATES_DIR...` (or pass an explicit `queue_path=`). If a real queue
artifact looks wrong after a test run, regenerate it canonically with
`scripts/run_durable_eval.py --run-id <focused_run> --rank --queue-dry-run`
(point `--rank-json/--rank-md` at the focused paths so the scout ranking isn't
overwritten). Report renderers should also accept both queue schemas
(`queue[]` dry-run vs legacy `candidates[]`).
