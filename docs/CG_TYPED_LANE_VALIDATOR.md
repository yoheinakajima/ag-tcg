# cg_typed lane validator

The tournament has **two distinct, non-overlapping validation lanes** for agent
tarballs. Pass 40 added the second one for public reference / benchmark agents.

## Why two lanes

| | stdlib lane (our candidates) | cg_typed lane (reference/benchmark agents) |
|---|---|---|
| Tarball shape | exactly top-level `main.py` + `deck.csv` | `main.py` + `deck.csv` + `cg/` SDK |
| Imports | **stdlib-only** (whitelist) | imports the `cg` SDK (native `libcg.so`) |
| Validation | `validate_candidate_tarball.py` + `validate_candidate_entrypoint.py` | `validate_cg_typed_tarball.py` |
| Execution | exec'd in-process (stdlib is safe) | optional import-smoke in a **hard-timeout subprocess** |
| Used to gate | our Kaggle submissions (pre-upload) | **never** — benchmark opponents only |

Our own Kaggle submissions must stay on the strict stdlib lane: exactly
`main.py` + `deck.csv`, stdlib-only imports, deterministic in-process exec, and the
`get_last_callable` entrypoint invariant. The reference agents from the competition
ship the `cg` SDK and `import cg`, which the stdlib lane **correctly rejects**. The
cg_typed lane is the parallel validator for that shape. **It never runs on, gates,
or relaxes our submission pipeline.**

## Static contract (`scripts/validate_cg_typed_tarball.py`)

All of the following are required for a `cg_typed` PASS (deterministic, no exec):

1. Top-level entries are exactly `main.py` + `deck.csv` + `cg/` (nothing else).
2. `cg/` contains `__init__.py`, `api.py`, `game.py`, `sim.py`, `utils.py`, and the
   native `cg/libcg.so`.
3. `deck.csv` has exactly 60 integer rows.
4. `main.py` (by AST) imports the `cg` SDK — the defining trait of this lane.
5. `main.py` (by AST) defines a top-level callable `agent`.

## Optional import-smoke (`--import-smoke`)

Imports the extracted `main.py` with `cg` on `sys.path` **in a hard-timeout
subprocess** and checks that a callable `agent` resolves. The subprocess boundary is
deliberate: the `cg` SDK loads native C via `ctypes`, which can hang and cannot be
interrupted by an in-process `SIGALRM`. The import-smoke is recorded as
`pass` / `timeout` / `skip_or_fail` and is **not** part of the static `ok` verdict —
a native-lib load failure in this environment is environmental, not a tarball
defect. Live gameplay is exercised separately by the cabt smoke (Pass 40 Part G).

## Lane separation is asserted, not assumed

`scripts/build_pass40_cg_typed_lane_validation.py` proves, every run, that:

- each reference tarball **passes** the cg_typed lane,
- each reference (cg_typed) tarball **fails** the stdlib tarball validator,
- a freshly packaged stdlib tarball (built in a temp dir from the frozen root
  `main.py` + `deck.csv`; root is never mutated) **still passes** the stdlib lane and
  **fails** the cg_typed lane.

If any of those flip, the lanes have overlapped or one has been weakened, and the
build exits non-zero.

## Usage

```bash
python scripts/validate_cg_typed_tarball.py path/to/agent.tar.gz            # static
python scripts/validate_cg_typed_tarball.py path/to/agent.tar.gz --import-smoke
```


<!-- PASS40_BENCHMARK_LANE_NOTE -->
## Pass 40 — public-reference benchmark lane (additive)

Pass 40 adds an `external_reference` **benchmark lane**: public Kaggle rule-based sample
agents registered on a SEPARATE ledger (`data/tournament/benchmark/benchmark_events.jsonl`)
and played against our schedulable candidates via `PublicBenchmark*` events. These
references are **benchmark opponents only** — never in our candidate pool, submission
queue, promotion, lifecycle, family-champion set, active-cap, mutation lineage, or any
"our best" ranking; the normal fold / scheduler / lifecycle never read the
`PublicBenchmark*` events, so folding is unbroken. Internal benchmark scores are NOT
Kaggle scores and NOT a strength claim. See `docs/PASS40_REFERENCE_AGENT_INTAKE.md` and
`data/reports/pass40_public_reference_agent_intake_report.md`.
