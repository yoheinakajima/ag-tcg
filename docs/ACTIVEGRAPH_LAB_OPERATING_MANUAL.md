# ActiveGraph Lab — Operating Manual

> **Read this first.** This is the canonical operating manual for the Pokémon TCG
> AI Battle Challenge ActiveGraph lab. Every future Replit / Codex / Claude
> session should read this document before doing anything. It records the golden
> invariants, environment pitfalls, the standard pipeline, and the lessons we have
> already paid for — so they are not re-learned the hard way.

---

## 1. Project purpose

- This repo competes in the **Kaggle Pokémon TCG AI Battle Challenge** (`cabt`).
- The goal is **deck + policy co-design** under the `cabt` environment: build a
  60-card deck and an agent policy that score well against the live opponent pool.
- The **ActiveGraph lab** is the research substrate. It records ideas, hypotheses,
  events, evaluations, and reports as a graph + artifact tree so that progress is
  auditable and reproducible across sessions.

---

## 2. Golden invariants

These are non-negotiable. Breaking one of these has cost us a pass before.

- **The submitted tarball is the unit of truth.** Local scores, surrogate evals,
  and intuition are secondary to what a tarball actually scores on Kaggle.
- **Root `main.py` and root `deck.csv` are historical/immutable** unless a
  candidate is explicitly promoted by a human. They match
  `data/baselines/v1_kaggle_349_8/`. Do not edit them.
- **Every candidate tarball must contain exactly top-level `main.py` + `deck.csv`.**
- **Every candidate tarball must pass `scripts/validate_candidate_tarball.py`.**
- The validator **must** test key-absent, select-null, empty-dict, and
  Struct-like deck-selection observations.
- **Every candidate must return exactly 60 card IDs** for deck-selection
  observations.
- **No candidate with a failed validator enters the queue, eval, or upload.**
- **Raw replays and official card data must not be committed.** (`data/cards/*.csv`,
  `data/kaggle_ref/*.csv`, raw replay payloads — all gitignored.)
- **Live Kaggle scores drift.** The active control must be **recomputed from the
  live score registry**, never hardcoded.
- **Local cabt surrogate eval is directional**, not equal to Kaggle score.
- **A replay-derived opponent deck is not the real opponent policy.** Surrogate
  decks approximate the *cards*, not the *decision-making*.
- **No upload unless explicitly human-approved.**

---

## 3. Known environment pitfalls

- **Kaggle CLI may not be on PATH.** In this environment `kaggle` is frequently
  *not installed* (`kaggle: command not found`). Sometimes it can be invoked
  through the Python package instead. Do not assume a refresh succeeded.
- **Live-score fetch may fail.** When it does, fall back to the last-known-good
  snapshot and **record that scores were not refreshed** — never silently present
  stale scores as current.
- **`build_live_score_registry.py` defaults to a stale CSV**
  (`status_before_pass10b.csv`). Always pass `--csv` with the real last-known-good
  snapshot (e.g. `status_before_pass11b.csv`) when refreshing offline, or it will
  flip the active control to an old score.
- **cabt runs through `kaggle_environments.make("cabt")`** even when importing
  `cabt` directly fails. Do **not** infer cabt absence from a module import alone.
- **Detached background shell jobs die between tool calls.** Use a Replit
  **workflow** (or a temp console workflow + sentinel file) for long evals; the
  bash tool has a ~120s cap.
- **Stale output files are dangerous.** Always check `run_id`, timestamps, game
  counts, and config before trusting any result file.
- **Local cabt may provide friendlier observation shapes than Kaggle production.**
  A local smoke test can pass while a key-absent deck-selection bug still ships.
- **The card DB is authoritative for id→name.** `data/cards/EN_Card_Data.csv` is
  the source of truth; the `evidence_card_names` field in `archetypes.yaml` has
  been wrong before (ids 678/756 swapped). Resolve names from the card DB.

---

## 4. Standard pipeline

1. **Fetch / refresh** the live score registry (or record fallback to
   last-known-good).
2. **Ingest** the replay inbox.
3. **Extract** replay decks.
4. **Classify** archetypes.
5. **Update** the meta pool.
6. **Generate candidates only from confirmed card IDs** (never invent ids).
7. **Validate** candidate tarballs.
8. **Evaluate** locally against replay-derived surrogate decks (directional).
9. **Rank** directionally.
10. **Report.**
11. Only then **consider a manual, human-approved upload.**

---

## 5. Current best-known state

> Always read these from the live artifacts, not from this paragraph. The values
> below are a snapshot for orientation; the bracketed paths are the truth.

- **Active control:** from `data/kaggle_uploads/live_score_registry.json` →
  currently `combo_full_safety_v3_fixed` @ **376.6** (scores not refreshed live
  this pass; reused last-known-good).
- **Replay count:** `data/meta_replays/replay_registry.json` → 9 episodes
  (3 our_win / 4 our_loss / 2 self-mirror; 7 real-opponent episodes).
- **Archetypes:** `data/meta_replays/archetypes.yaml` →
  `metal_ex_zacian_ramp` (confirmed), `water_kyogre_abomasnow_maxbelt`
  (confirmed), `unknown_ex_tempo` (provisional — now decomposed; see
  `data/meta_replays/unknown_ex_tempo_decomposition.json`),
  `water_kyogre_abomasnow_passive_mirror` (ours / diagnostic mirror).
- **Best-known submission:** `combo_full_safety_v3_fixed.tar.gz`.
- **Current blockers:** chaos lane is blocked (no confirmed payoff card +
  measurable trigger); subfamily decks are surrogates only; no candidate has
  cleared the promotion gate.

---

## 6. How to run common commands

```bash
# Root package verify (must show root unchanged + deck valid)
python scripts/package_submission.py --verify-only
cmp main.py data/baselines/v1_kaggle_349_8/main.py && echo "root main.py unchanged vs v1"
cmp deck.csv data/baselines/v1_kaggle_349_8/deck.csv && echo "root deck.csv unchanged vs v1"

# Candidate tarball validation (key-absent / select-null / empty-dict / Struct-like)
python scripts/validate_candidate_tarball.py <path/to/candidate.tar.gz>

# Replay inbox ingestion + archetype extraction + analysis + meta pool
python scripts/ingest_replay_inbox.py
python scripts/extract_meta_archetypes.py
python scripts/analyze_kaggle_replays.py
python scripts/update_meta_pool_from_replays.py

# Live score registry build — ALWAYS pass the last-known-good CSV when offline
python scripts/build_live_score_registry.py --csv data/kaggle_uploads/status_before_pass11b.csv

# Pass 12 meta-candidate eval (directional)
python scripts/run_pass12_eval.py        # see script flags for budget/seat options

# Report build (site + markdown reports)
python scripts/build_report_site.py

# Tests — run in small groups (do NOT run the whole suite blindly)
python -m pytest tests/test_pass13_operating_manual.py -q
python -m pytest tests/test_pass12_meta_eval.py -q

# Long evals: use a Replit workflow, NOT a detached background shell.
# Detached jobs die between tool calls; the bash tool caps at ~120s.
```

---

## 7. Git hygiene

**Safe to commit:**
- scripts, source, tests, docs
- generated **summaries/reports** (markdown, site html, json *analysis* outputs)
- meta pool YAML, archetype YAML (names + ids, no raw payloads)
- decomposition JSON/MD (fingerprints + names + counts, no raw card CSV)

**Must NOT be committed:**
- raw replay payloads (gitignored under `data/meta_replays/` raw inputs)
- official card data: `data/cards/*.csv`, `data/cards/*.pdf`, `data/kaggle_ref/*.csv`
- Kaggle credentials / API tokens / Replit secrets
- the live score **registry json** is gitignored (rebuild it from a CSV snapshot)

**Maybe-optional generated artifacts:** eval result JSON, site HTML — useful for
traceability, safe to commit, but regenerable.

**Replit secrets policy:** never print, echo, or commit secret values. Use the
environment-secrets tooling. `KAGGLE_KEY` / `KAGGLE_USERNAME` exist as secrets but
the CLI may still be absent.

---

## 8. Upload checklist (STRICT — complete every line before any Kaggle upload)

1. [ ] active control refreshed **or** explicitly marked stale (with reason)
2. [ ] candidate tarball path recorded
3. [ ] `validate_candidate_tarball.py` **PASS** for that exact tarball
4. [ ] tarball contents check: exactly top-level `main.py` + `deck.csv`
5. [ ] candidate `main.py` uses **stdlib only / no forbidden imports**
6. [ ] candidate strategy evidence documented (why it should beat active control)
7. [ ] **no root mutation** (`cmp` root `main.py`/`deck.csv` vs v1 baseline)
8. [ ] **no raw data committed** (replays / card CSV / creds)
9. [ ] exact Kaggle submission message prepared
10. [ ] **one upload only**, and only with explicit human approval

---

## 9. Lessons learned so far

- **Deck-loader bug.** Early candidates failed because the deck wasn't loaded on
  the Kaggle agent path — fixed by an explicit path fallback (v1).
- **Key-absent deck-selection bug.** Kaggle production sends deck-selection
  observations whose keys differ from local; agents must return 60 ids even when
  the expected key is absent/None/empty.
- **Local smoke masked the bug.** Local cabt gave friendlier obs shapes, so smoke
  passed while production failed. The validator now tests key-absent / select-null
  / empty-dict / Struct-like obs.
- **Score drift.** A candidate's live score moved between passes; the active
  control must be recomputed from the registry, never assumed.
- **v2 local improvement was not stable live.** A local win-rate gain did not
  reproduce on Kaggle — surrogate eval is directional only.
- **Combo safety underperformed, then drifted.** `combo_full_safety_v3_fixed`
  was once live-rejected @294, later became the active control @376.6 — same
  tarball, different live score. Trust the registry, not memory.
- **Mirror overfit.** Tuning against our own mirror deck does not transfer to the
  real opponent pool; self-mirror is diagnostic only.
- **unknown_ex_tempo dominance.** A single provisional bucket carried ~60% of
  eval weight and was too broad to guide design — addressed by the Pass 13
  decomposition into evidence-grounded subfamilies.
- **Workflow requirement for long evals.** Detached background shells die between
  tool calls; long evals must run under a Replit workflow.
