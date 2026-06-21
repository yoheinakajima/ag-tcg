# Candidate Generation v0 (Pass 42)

> **Scope.** A controlled, **LOCAL-only**, **deterministic**, **probation-only**
> candidate *factory* for the standing tournament daemon. It generates at most a
> few NEW *internal* candidates from eligible *internal* families using
> deterministic, stdlib-safe mutation operators, validates each through hard
> gates, and admits only the passing ones to the pool as `status=probation`.
>
> **This pass never makes a strength claim and never touches Kaggle.** It is
> internal-diagnostics infrastructure. Admission to `probation` means "eligible to
> be *evaluated* by the local engine", NOT "good", "promoted", or "submitted".

---

## 1. Hard guardrails (non-negotiable)

The factory is bounded by guardrails enforced in code, asserted by the preflight
(Part A), re-checked by the validation gates (Part E), and covered by tests
(Part I). Every one of these is a *must-not*:

- **NO Kaggle upload / submit / auto-submit.** No `SubmissionUploaded`,
  `KaggleScoreUpdated`, no call into `package_submission.py` upload paths.
- **NO GitHub push.**
- **NO root mutation.** `main.py` / `deck.csv` at repo root stay byte-identical to
  `data/baselines/v1_kaggle_349_8` before and after the run.
- **NO tarball deletion or overwrite** — except a no-op rewrite that is
  byte-for-byte identical by SHA-256 (idempotent rerun).
- **NO public-reference involvement.** The five Pass-40 public references are
  *benchmark-only*: never a candidate, never a lineage parent/source, never
  queued, never promoted, never mutated. They are absent from `candidate_pool.json`.
- **NO `special_pilot_only` decks** as sources or products.
- **NO LLM-materialized candidates.** An LLM *proposal-only* stub exists; it
  returns suggestions as inert data and materializes nothing.
- **NO promotion / queue / active-cap change.** New candidates enter ONLY as
  `probation`. No `active` / `family_champion` / `portfolio_anchor` / `held_probe`
  is created, changed, or retired. No `CandidatePromoted` / `SubmissionQueued`.
- **Never start the root `Start application` workflow** (frozen Kaggle entrypoint;
  not-started is EXPECTED).

## 2. Budgets

| Budget | Value |
| --- | --- |
| `max_new_candidates_per_run` | 3 |
| max per family per run | 1 |
| max admitted total (v0) | 3 |

Budgets are enforced in the generation **plan** (before any tarball is built) and
re-asserted at admission. Admission can stop short of the budget and the pass is
still a success (see §10, the final decision).

## 3. Eligible vs ineligible sources

A *source* is an existing internal candidate whose deck/policy we mutate. A family
is *eligible* when it has at least one eligible source.

**Eligible source** — ALL of:
- status in `{active, held_probe, family_champion, portfolio_anchor}` (an
  established candidate). **`probation` and `generated_*` candidates are NOT
  eligible sources** — this keeps the eligible set, and therefore the deterministic
  seed, *stable across reruns even after admission* (idempotency, §8).
- internal (NOT a public reference; references never appear in the pool anyway).
- NOT `special_pilot_only` / `retired` / `quarantined` / `invalid`.
- tarball exists and is a **stdlib-lane** artifact: exactly top-level
  `main.py` + `deck.csv` (no bundled `cg/` SDK). This guarantees the generated
  child is stdlib-safe.

**Ineligible (excluded) — examples in the current pool:**
- `toxic_trap_poison_lock`, `deckout_carousel_durant_v2` — `special_pilot_only`.
- `core_pilot_water_v2_runtime` — `retired`.
- all 5 Pass-40 public references — benchmark-only.

**Eligible families (verified):** water, dragapult (spread is an UNSUPPORTED
mechanic — noted caveat), lightning, diamond, mega_venusaur, mega_charizard,
mega_gardevoir.

## 4. Card classification (honest, authoritative)

Card type is read from the authoritative CSV column
**`Stage (Pokémon)/Type (Energy and Trainer)`** via `CardDB.get(id)`, matched by
**exact value** (never substring — `"Pokémon Tool"` contains `"pok"`, so a naive
pokemon substring check would mis-bucket trainers):

| Column value | Bucket |
| --- | --- |
| `Basic Energy` | `energy` |
| `Basic Pokémon` | `basic_pokemon` |
| `Stage 1 Pokémon`, `Stage 2 Pokémon`, `Mega …`/`Stage …` | `evolution_pokemon` |
| `Item`, `Pokémon Tool`, `Supporter`, `Stadium` | `trainer` |

- **Energy** is corroborated by the legality rule (`count > 4` ⇒ basic energy,
  the only copy-limit-exempt card type). The column and the count agree on every
  deck in scope; if a card is unknown to the DB, `count > 4` is the fallback.
- **Draw / search trainers** are sub-classified conservatively from the card name
  + `Effect Explanation` using a small documented keyword set
  (`draw`, `search your deck`, …). When a deck has no clear draw/search pair, the
  draw/search operator is simply *not applicable* to it (no fake classification).

## 5. Mutation operators

All operators are **source-ID-only**: they redistribute *copy counts among card
IDs already present in the SOURCE deck*. No new/invented IDs (sibling-family
verified-ID transfer is deferred to v1). All preserve **exactly 60 cards** and
deck legality (60 integer ids; non-energy copies kept ≤ 4; energy exempt). Each
returns the new deck (or a policy delta), a structured `deck_delta` /
`policy_delta`, and an applicability reason.

1. **`basic_density_adjustment`** — increase Basic-Pokémon density: `+1` to a
   chosen Basic Pokémon with `count < 4`, `−1` from a chosen basic-energy id with
   `count` above a floor. Deterministic choice (lowest current count, then lowest
   id). Applicable when a Basic Pokémon has room and energy has slack.
2. **`energy_ratio_adjustment`** — shift the energy ratio: `−1` basic energy,
   `+1` to a chosen non-energy id with `count < 4`. Applicable when energy `> floor`
   and a non-energy card has room.
3. **`draw_search_ratio_adjustment`** — shift the trainer draw/search ratio: `−1`
   from a search trainer with `count ≥ 2`, `+1` to a draw trainer with `count < 4`
   (or vice-versa, deterministic). Applicable when the deck has both a draw and a
   search trainer with the needed slack.
4. **`conservative_policy_weight_delta`** *(non-admitted regression example)* —
   deck UNCHANGED; nudges one stdlib `_POSITIVE` / `_NEGATIVE` keyword weight by a
   small conservative delta. Generated and validated to exercise the policy path,
   but **not admitted** in v0 (its effect may be inert because the actual last
   callable is the core-pilot playbook override; proving non-inertness is deferred).
5. **`noop_sentinel`** *(rejected by design)* — returns the source unchanged. Built
   and run through the gates to PROVE the duplicate/inert detector rejects it.

The three deck operators (1–3) are the only ones eligible for admission in v0.

## 6. Deck mutation mechanics (both representations)

A candidate `main.py` reads `deck.csv` at runtime (cwd-/`__file__`-relative) with
an `_EMBEDDED_DECK = [...]` fallback baked into the source. A deck mutation
rewrites **both** representations so the artifact is internally consistent and its
`main_fingerprint` genuinely changes:

- `deck.csv` — one integer id per line, 60 rows.
- `_EMBEDDED_DECK` — a narrow parser/renderer replaces only the
  `_EMBEDDED_DECK = [ … ]` literal block (10 ids per line), leaving the rest of
  `main.py` byte-identical. The rewritten source is re-parsed (`ast.parse`) and the
  extracted embedded list is asserted equal (as a multiset) to the new `deck.csv`.

The validators then prove the agent's *returned* deck multiset ==
`deck.csv` == extracted `_EMBEDDED_DECK`.

## 7. Candidate identity, provenance & versioning

- **Generated id:** `generated_<family>_<source_short>_<operator>_v1`.
- **Output dir:** `data/submissions/generated_pass42/` (never the source dirs).
- **Lineage manifest** records, per candidate: `source_candidate_id`,
  `source_tarball_sha256`, `operator`, `parameters`, `deck_delta` / `policy_delta`,
  `generated_candidate_id`, `generated_tarball_sha256`, validation outcome.
- **Provenance events** (see §9) carry the operator, parameters, parent id, and
  fingerprints.

## 8. Determinism & idempotency

- **Seed** = `sha256(pass_id + catalog_version + sorted eligible source ids +
  each source's tarball/main/deck sha256)`. It is a pure function of the *inputs*,
  NOT wall-clock and NOT drifting finished-game ids. Because `probation` /
  `generated_*` are excluded from sources (§3), admitting candidates does not
  change the seed.
- **Plan** is a pure function of `(pool, card_db, catalog_version, pass_id)` plus
  the seed for tie-break rotation. Families are processed in sorted order; each is
  assigned the first applicable operator (rotated by seed for diversity), capped at
  the budget.
- **Tarball writer is deterministic** (fixed mtime/uid/gid/order) so the same plan
  produces a byte-identical tarball (identical SHA-256).
- **Rerun** loads the existing plan/manifest, rebuilds identical tarball SHAs,
  re-emits nothing already present (events deduped by generated id + tarball sha),
  and never overwrites a differing tarball or deletes anything.

## 9. Event vocabulary

Two **additive** event types (in `EventType`), both `no_upload=true`, written to
the **main lab ledger**:

- `CandidateGenerated` — a NEW candidate was produced (operator, params, parent,
  fingerprints).
- `CandidateValidationFinished` — the validation-gate outcome for a candidate.

Both are **purely informational provenance**. `CandidatePool.from_events()` folds
ONLY `TournamentParticipantRegistered` (full snapshot) + `CandidateStatusChanged`
(status), so the new types can **never** be mis-folded as a promotion / queue /
active-cap signal. Admission emits, per admitted candidate:
`CandidateGenerated` + `CandidateValidationFinished` + a canonical
`TournamentParticipantRegistered` (full `Candidate.to_dict()`, `status=probation`),
then `pool.save()`. The pass **never** emits `CandidatePromoted`,
`SubmissionQueued`, `SubmissionUploaded`, or `KaggleScoreUpdated`.

## 10. Validation gates (Part E)

A candidate is admitted only if it passes ALL of:

1. tarball shape — exactly top-level `main.py` + `deck.csv`.
2. entrypoint invariant — last callable returns the 60-card deck on every
   deck-selection shape and legal indices on gameplay; no forbidden imports.
3. deck legality — 60 cards, all integer ids, no invented ids (⊆ source ids), copy
   limits respected.
4. embedded-deck consistency — returned deck == `deck.csv` == extracted
   `_EMBEDDED_DECK`.
5. smoke vs self and vs one source parent — one cabt game each, no INVALID/ERROR.
6. no public-reference leakage — no reference id anywhere in lineage.
7. duplicate detection — deck/policy not identical to an existing candidate
   (rejects `noop_sentinel`).
8. **meaningful change** — a real deck-composition delta (deck operators) OR proven
   non-inertness (policy operator). A no-op is rejected.
9. root re-check — root `main.py`/`deck.csv` still byte-identical.
10. event audit — no upload/submit/promote/queue event emitted.

Rejected candidates are recorded with a reason; their tarballs are kept (never
deleted), simply not registered.

## 11. Final decision

The pass succeeds with one of:

- **`candidate_generation_v0_enabled`** — 1–3 candidates generated, validated, and
  admitted as `probation`; OR
- **`generation_infrastructure_ready_no_admissions`** — the infrastructure is
  correct and safe but nothing qualified for admission this run.

Both are PASS outcomes. The pass FAILS only if a guardrail is violated or the
infrastructure is incorrect.
