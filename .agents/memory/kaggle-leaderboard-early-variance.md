---
name: Kaggle leaderboard early-episode variance
description: Why a fresh Pokémon-TCG-AI submission's publicScore is unreliable until many leaderboard episodes accrue
---

A freshly uploaded submission to the `pokemon-tcg-ai-battle` competition can post a
very high `publicScore` early, then drift substantially DOWN as more leaderboard
episodes are played and the score converges.

**Concrete instance:** a Water "anti-disruption pivot" submission read 520.8 shortly
after upload (which looked like a +157 lead over the rest of the family), then settled
to 358.7 once more episodes accrued — the live best was actually `submission.tar.gz`
@ 363.0, i.e. the pivot was within noise (Δ −4.3), not ahead.

**Why:** the leaderboard score is an average over a growing pool of stochastic
self-play episodes; with few episodes the variance is large and the early reading is
an artifact, not a signal.

**How to apply:** treat any just-uploaded score as provisional. Do not promote,
"protect a lead", or pick a current_best off an early reading. Re-read the score after
more episodes settle, and compare candidates only against the highest *complete*
publicScore (the active-control rule), never a hardcoded label. When two submissions
are within a few points, call them tied and lean on offline behavioural evidence.
