---
name: surrogate eval is directional only
description: How much to trust local meta-pool eval results for promotion decisions.
---

Local focused/meta-pool eval pits candidates against subfamily decks piloted by a GENERIC
surrogate policy, not the real opponent policy. Results are directional only and never equal
a live Kaggle score.

**Why:** A wider context-coverage candidate (v3) scored LOWER than the narrower reference
(v2) under surrogate eval (0.62 vs 0.678 weighted; 0.35 vs 0.55 vs-anchor, overlapping Wilson
intervals). More coverage is not automatically better, and surrogate noise can't separate them.

**How to apply:** Never auto-promote/upload on surrogate evidence alone. Keep the dry-run
queue at upload_performed:false / auto_submit:false / manual_approval:true and queue <=1.
Require real-policy (live Kaggle) evidence before promoting any context-expansion candidate.
