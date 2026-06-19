# ActiveGraph memory index

Pointers to topic files in this directory. Each line: `- [Title](topic.md) — hook`.

## cabt engine / local evaluation
- [cabt local evaluation gotchas](cabt-local-eval.md) — How to correctly run kaggle_environments "cabt" games locally for PTCG agent eval.
- [cabt eval harness quirks](cabt-eval-harness.md) — Non-obvious runtime traps when running cabt PTCG self-play games locally for candidate evaluation.
- [cabt agent runtime quirks](cabt-agent-runtime.md) — How the cabt Kaggle engine loads and calls the agent — non-obvious env behavior.
- [cabt option-type semantics + RB diagnosis](cabt-option-and-rb-diagnosis.md) — What cabt option `type` integers mean, and why an aggro energy/attack rescue was not built.
- [In-process cabt eval dies silently on C-level crash](in-process-eval-c-crash.md) — Why the cabt batch MUST use a per-game subprocess runner, never in-process.
- [Long cabt eval runs](long-cabt-eval-runs.md) — Run multi-game leagues/meta-sanity via managed workflow + sentinel + batched subprocess worker; never nohup, never in-process loops.
- [Long-running jobs in this Repl](long-running-jobs.md) — How to run >120s jobs when bash/background processes get orphan-killed.
- [Sandbox kills background processes](sandbox-kills-background-procs.md) — Long durable eval runs must run foreground in bounded chunks, not nohup/background.
- [Subprocess script-dir stdlib shadowing](subprocess-stdlib-shadowing.md) — sys.path fix for "relative import with no known parent package" in per-game child subprocesses.
- [Kaggle cabt / OpenSpiel env quirks](kaggle-cabt-env-quirks.md) — Why local cabt self-play masks the deck-return bug and the full smoke can't run in one sandbox tool call.

## Kaggle submission / entrypoint
- [Compiled-agent entrypoint is the LAST callable](kaggle-compiled-agent-entrypoint.md) — Appending code after the agent fn silently breaks a compiled submission.
- [get_last_callable entrypoint ordering](kaggle-entrypoint-ordering.md) — Deck-safety wrappers must use a fresh name; how the active control's wrapper became inert.
- [Kaggle cabt deck-selection observation shape](kaggle-deck-selection-obs.md) — Candidate agents must detect the deck-selection step without assuming a dict.
- [Eval validator pre-filter + anchor pattern](eval-validator-prefilter-anchor.md) — A live submission failing the entrypoint validator stays a directional anchor, never a promotion target.

## Core pilot / policy / playbooks
- [core-pilot context wiring](core-pilot-context-wiring.md) — Rules for expanding compiled core-pilot runtime context coverage safely.
- [Policy override layers](policy-override-layers.md) — How injected candidate policy layers work; fixture decisions land in the embedded heuristic path.
- [Playbook validator card-id coverage](playbook-validator-card-ids.md) — Any playbook section with card-id lists must be registered for validation or its ids go unchecked.
- [Card DB energy detection](card-db-energy-detection.md) — How to recognize basic energy cards for copy-limit / deck-building checks.
- [Replay fixture gate](replay-fixture-gate.md) — How the pre-cabt decision-fixture gate grades candidates; why v2 fails some checks by design.

## Meta / archetypes / evaluation trust
- [surrogate eval is directional only](surrogate-eval-directional.md) — How much to trust local meta-pool eval for promotion decisions.
- [Two archetype lenses](archetype-two-lens.md) — Why the meta archetype layer exists twice and must not be unified.
- [meta_pool.yaml evolves per pass](meta-pool-evolution.md) — Each Pass rewrites meta_pool.yaml and updates the prior pass's state-assertion tests.
- [Unknown-EX tempo decomposition](unknown-ex-decomposition.md) — How the unknown_ex_tempo bucket splits; authoritative source for card id->name.

## Lab ops / reporting / scores
- [ActiveGraph Strategy Lab invariants](activegraph-strategy-lab.md) — Safety invariants and gotchas for the lab wrapped around the immutable v1 baseline.
- [ActiveGraph lab script operations](activegraph-lab-ops.md) — Operational gotchas running the experiments lab scripts (generate/run/rank/queue/report).
- [report honesty contract](report-honesty-contract.md) — Honesty rules the report renderers must obey so they never fabricate conclusions.
- [Report candidate gate labels](report-candidate-gate-labels.md) — Candidate gate labels must come from the hard fixture gate, not package/smoke metric keys.
- [ledger status projection](ledger-status-projection.md) — Run/game status is derived; every state must be in the schema map or it vanishes from inspect.
- [Submission-queue artifact test leak](queue-artifact-test-leak.md) — Queue-builder tests must redirect QUEUE_JSON + CANDIDATES_DIR or they clobber the real artifact.
- [ActiveGraph live scores drift](activegraph-canonical-scores.md) — v1/v2 baseline live scores are point-in-time; archive dir names are historical anchors, not current scores.
- [Live score registry build input](live-score-registry-build.md) — build_live_score_registry.py default CSV is stale; pass --csv with last-known-good.
- [chaos telemetry observability](chaos-telemetry-observability.md) — What the cabt harness exposes about the opponent; why chaos seams are partially_observable.
