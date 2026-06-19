---
name: effect-loop-head-diagnosis
description: How to correctly classify a cabt effect-loop (Venusaur stall) — inspect the loop HEAD context, not just the inner sub-loop.
---

# Effect-loop classification: read the loop HEAD, not just the inner contexts

When a deck (e.g. mega Venusaur tank) stalls in a repeated effect-loop and never
attacks, classify the loop by the **head context** the pilot keeps returning to —
not by the inner contexts where the visible churn happens.

**The trap:** the Venusaur stall churns through ctx33 (move-energy) → ctx21
(place) thousands of times per turn. Looking only at ctx33/21 makes it look like a
`forced_engine_loop` (the engine forcing the pilot in circles). That read is WRONG.

**The correct finding:** the loop HEAD is ctx0. There the pilot is offered exactly
two option classes — `('end', 'in_play_action')` — and picks `in_play_action`
1958/1958 times, NEVER the available `end` option. So it is an
`optional_loop_with_exit`: a legal exit IS observable and selectable at the head,
the base pilot just always declines it. `in_play_action` then forces the
ctx33→ctx21 sub-loop with zero board progress until the step cap.

**Why:** misclassifying it as forced sends you hunting for an engine/legality bug
that does not exist; classifying it as optional-with-exit makes the fix a cheap
runtime exit guard (force the engine's own end option type 12/14 after a
static-board-signature repeat threshold), with no deck change and no invented IDs.

**How to apply:** for any suspected effect-loop, first find the context the cycle
returns to (the head), enumerate its option classes, and check whether a legal
terminating option (end / pass) is present-but-declined there. Only call it
`forced_engine_loop` if NO legal exit exists at the head. The exit-observability at
the head is also the feasibility gate for building an exit-guard candidate.
