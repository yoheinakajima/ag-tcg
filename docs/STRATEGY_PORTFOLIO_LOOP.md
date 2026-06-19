ActiveGraph Strategy Portfolio Loop

LOCAL ONLY. NO Kaggle upload by default. This document is the durable operating
model for how the ActiveGraph lab maintains a portfolio of strategy families and
iterates candidates inside them. It is the source-of-truth description that the
machine-readable registry (experiments/strategy_families.yaml) and the per-pass
portfolio state (data/experiments/pass19_strategy_portfolio_state.{json,md})
instantiate. Nothing in this loop uploads or submits anything to Kaggle; the only
path to Kaggle is a separate, human-approved upload-readiness pass (step 9).

THE LOOP (nine stages)

1. Family registered
   A strategy family (a deck shell + intended plan) is registered in
   experiments/strategy_families.yaml with a hypothesis, strengths, risks and a
   next experiment. Emits StrategyFamilyRegistered.

2. Candidate iteration created
   A concrete candidate (deck + embedded playbook, piloted by the generic core
   pilot) is created inside a family, with an explicit parent_candidate and a
   one-line hypothesis describing the intended behavioral change. Emits
   StrategyIterationCreated.

3. Fixture gate
   The candidate must pass the shared core-competency fixtures (no regression vs
   parent) plus any targeted fixtures written for the behavior it changes. A
   candidate that regresses the core gate is not league-eligible. Emits
   StrategyFixtureAdded for new fixtures.

4. Parent/child head-to-head
   The candidate plays its OWN parent directly, seat-swapped, over enough games to
   read a trend. This is the single most important compatibility signal for a
   refinement: a child that improves an aggregate league but loses its direct
   parent H2H has changed the policy in a way that is field-specialized, not
   strictly better. Emits ParentChildComparisonStarted / ParentChildComparisonFinished.

5. Internal league
   The candidate, its parent, sibling refinements and a stable reference play a
   seat-swapped round robin. This measures internal deck/pilot COMPATIBILITY only.
   It is NOT a Kaggle leaderboard. Emits InternalLeagueStarted / InternalLeagueFinished.

6. Replay-derived meta sanity
   The candidate is stress-tested against surrogate opponents built from
   replay-derived deck lists (piloted by a generic surrogate, not the real
   opponent policy). This is DIRECTIONAL stress evidence only.

7. Strategy decision
   A decision is recorded per family: keep parent, keep child as research lead,
   promote a refinement to research lead, need more H2H, blocked, candidate for
   deeper confirmation, or upload-not-recommended. Emits StrategyDecisionRecorded /
   StrategyPromotionDecision.

8. Optional deeper confirmation
   If a refinement beats its parent H2H AND holds aggregate league and meta sanity,
   it may be queued for a longer confirmation run before any human considers upload.

9. Manual Kaggle probe (human-approved only)
   Upload/submit happens only after a human approves and only in a separate
   upload-readiness pass. No automated step in this loop ever uploads.

PER-FAMILY TRACKING FIELDS
Each family in the registry tracks: family_id, status, current_best,
parent_candidate, child_iterations, fixtures, league results, meta sanity results,
blockers, next experiment, upload posture.

DECISION RULES (binding)
- A child CANNOT replace a parent if it improves the aggregate league but collapses
  the direct parent head-to-head, UNLESS a report explicitly accepts that tradeoff
  and names it (e.g. "field-specialized: wins the field, loses the mirror").
- Internal league results are COMPATIBILITY evidence, not Kaggle evidence.
- Meta sanity results are DIRECTIONAL stress evidence, not Kaggle evidence.
- A candidate that wins aggregate but loses parent H2H is described as
  "field-specialized" / "field-driven", never as "strictly better".
- Kaggle upload requires manual human approval AND a separate upload-readiness pass.
  No pass that runs this loop may upload.

CURRENT_BEST SEMANTICS
current_best is a registration-time snapshot of the family's best-known candidate.
It is updated by an explicit promotion decision (step 7), not automatically by a
single league or meta-sanity result. A research lead that loses its parent H2H is
recorded as a research lead, not promoted over the parent as current_best.
