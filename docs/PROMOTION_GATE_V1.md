# Promotion Gate v1 — internal lifecycle gate for the standing tournament

> **Internal self-play diagnostics only. NOT a Kaggle leaderboard and NOT predictive
> of leaderboard placement. NO upload, NO submit, NO Kaggle queue.**

The Promotion Gate is a *conservative, evidence-gated recommender* that proposes one
lifecycle action per candidate in the standing Pokémon TCG tournament. It is **not** a
scheduler and **not** an optimizer. It reads the candidate registry (rebuilt from the
event ledger) plus the folded `GameFinished` projections, and produces
recommendations. By default it changes nothing (`dry-run`). Under an explicit,
separately-gated `--apply` it emits only `CandidateStatusChanged` status marks to the
**local** ledger — it never deletes a tarball, never touches production, and never
emits any Kaggle/upload/submit/promotion event.

Implementation: `src/ptcg_activegraph/tournament/promotion.py`
Runner: `scripts/run_tournament_promotion_gate.py`
Machine-readable policy: `data/experiments/pass43_promotion_gate_policy.json`

## Statuses and actions

Each candidate receives exactly one action:

| Action | Meaning | Emits a status change? |
|---|---|---|
| `stay_probation` | Evidence accrued but margin not cleared; keep on probation. | no |
| `activate` | `probation → active`: every activate gate passes. | yes |
| `promote_family_champion` | `active → family_champion`: stricter gate passes. | yes |
| `retire_to_retired` | `→ retired`: clearly underperforms parent over adequate N. | yes |
| `quarantine` | `→ quarantined`: complete/high hard-failure evidence. | yes |
| `insufficient_evidence` | Not enough games / anchor / parent H2H to decide. | no |
| `blocked_protected_status` | `family_champion`/`portfolio_anchor`/`held_probe`; never demoted. | no |
| `blocked_invalidity` | `retired`/`quarantined`/`special_pilot_only`/`invalid`; not a subject. | no |
| `blocked_public_reference` | Public reference; benchmark-only, never a subject. | no |

## Core principles (locked; never weaken to force a promotion)

1. **Raw win-rate never promotes.** Activation requires a *Wilson lower bound* that
   clears the direct-parent baseline (0.50) by a margin — a noisy high win-rate over
   few decisive games cannot clear the bound.
2. **Direct head-to-head superiority is required, not aggregate out-farming.**
   Activation requires the candidate to beat its *parent* head-to-head (the
   parent-H2H Wilson lower bound must clear the baseline by the margin), and
   champion promotion requires beating the *incumbent champion* head-to-head
   (enough direct decisive games whose Wilson lower bound clears the champion). A
   candidate that runs up a strong aggregate record against weak opponents while
   losing to its parent/champion is never promoted.
3. **Sample-size minimums are hard.** Total games, decisive games, anchor games (and
   anchor-decisive), and seat-balanced parent head-to-head games must all be met
   *before* any superiority test is even considered.
4. **Public references are benchmark-only.** They never enter the promotion subject
   set — neither as a candidate, parent, scheduled participant, nor promotion target.
5. **Protected statuses are never demoted** by this gate (`family_champion`,
   `portfolio_anchor`, `held_probe`).
6. **Tarballs are immutable.** Lifecycle is a status mark only; tarballs are never
   deleted or overwritten.
7. **Deck change must be real.** Activation requires a proven deck-delta (or proven
   non-inertness) for the candidate — an inert variant cannot be promoted on noise.

## Decision order

For each candidate the gate evaluates, in order:

1. `blocked_public_reference` if it is a public reference.
2. `blocked_invalidity` if its status is never-schedulable
   (`retired`/`quarantined`/`special_pilot_only`/`invalid`).
3. `blocked_protected_status` if its status is protected.
4. `quarantine` if there is complete hard-failure evidence (every game invalid) or a
   hard-fail rate at/above the quarantine rate over an adequate sample. Draws are
   non-decisive but are **not** failures.
5. Compute the shared minimum-evidence gate (total / decisive / anchor / parent H2H +
   seat balance / hard-fail rate). If full evidence is present **and** the Wilson
   *upper* bound is clearly below the parent baseline by the retire margin →
   `retire_to_retired`.
6. If the minimum-evidence gate is unmet → `insufficient_evidence`.
7. With sufficient evidence:
   - **probation** → `activate` iff deck-delta/non-inertness is proven **and** the
     *aggregate* Wilson lower bound clears `parent_baseline + activate_wilson_margin`
     **and** the *direct parent-H2H* Wilson lower bound clears the same baseline+margin
     **and** the anchor comparison is non-inferior by CI; otherwise `stay_probation`
     (a candidate that out-farms weak opponents but loses to its parent head-to-head
     stays on probation).
   - **active** → `promote_family_champion` iff the stricter champion gate passes
     (larger N, parent+family and anchor minimums, an existing champion baseline, an
     *aggregate* Wilson lower bound clearing that baseline by the champion margin, **and**
     a *direct champion-H2H* of at least `champion_min_h2h_games` decisive games whose
     Wilson lower bound clears the champion by the margin); otherwise
     `insufficient_evidence`. A candidate is never crowned over an incumbent it never
     beat — or never played — head-to-head.

## Thresholds

The locked v1 thresholds live in `PromotionThresholdsV1` and are serialised verbatim
into `data/experiments/pass43_promotion_gate_policy.json`. Highlights:

- `activate_min_total_games = 40`, `activate_min_decisive_games = 30`
- `activate_min_anchor_games = 10` (`activate_min_anchor_decisive = 8`)
- `activate_min_parent_h2h_games = 20`, seat balance `>= 25%` on the weaker seat
- `max_hardfail_rate = 0.05`
- `parent_baseline = 0.50`, `activate_wilson_margin = 0.03`,
  `anchor_noninferior_margin = 0.03`
- family-champion: `champion_min_total_games = 80`,
  `champion_min_parent_family_games = 40`, `champion_min_anchor_games = 20`,
  `champion_min_h2h_games = 20` (direct decisive games vs the incumbent champion),
  `champion_margin = 0.05`
- retire: `retire_wilson_high_margin = 0.03`
- quarantine: `quarantine_hardfail_rate = 0.50` over `quarantine_min_n_for_rate = 20`

## Apply mode (conservative)

`--apply` emits a `CandidateStatusChanged` **only** when all of the following hold:

- the recommendation is actionable
  (`activate`/`promote_family_champion`/`retire_to_retired`/`quarantine`);
- the Part A root/prod safety preflight is green (`preflight_safe` and not
  `stop_required`);
- the candidate is not a public reference and is not already at the target status
  (idempotent);
- the new status is a local lifecycle mark — never a Kaggle/upload/submit/promotion
  event (the ledger itself also refuses those types).

After applying, the runner rebuilds the pool from the ledger, saves
`candidate_pool.json`, and refreshes the **local** `storage_manifest.json` in lockstep
(`no_upload`, remote untouched). With no accrued placement evidence the expected
outcome is `apply_skipped = true, reason = insufficient_evidence`.
