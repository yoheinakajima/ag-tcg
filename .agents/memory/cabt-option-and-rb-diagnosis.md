---
name: cabt option-type semantics + Raging Bolt 0-30 diagnosis
description: What cabt option `type` integers mean, and why the Raging Bolt aggro rescue was NOT built
---

# cabt option model (observed, not fully documented in code)
Each option in `obs['select']['options']` is a dict with an integer `type`. The base
agent's `_OPTION_TYPE_SCORES` weights them but does not label meanings. Observed:
- `type == 13` = **Attack** (carries `attackId`; e.g. Raging Bolt's only offered attackId was 71). This is `_ATTACK_TYPE`.
- `type == 8`  = discard-context option (by far most common in play).
- `type == 7`  = search/draw to-hand.
- `type == 14` = penalized/undesirable action (negative score).
- `type` 0/1/2 = setup/neutral (active/bench placement) selections.
- **Energy attach** has no dedicated `type` constant: it is a hand **basic-energy**
  option (`resolve_option_card` ∈ {1..7}) that ALSO carries an in-play target
  (`resolve_option_target` via inPlayArea/inPlayIndex). Classify attaches that way.
- `select.context == 0` = broad Main; the core pilot intentionally **delegates** ctx 0
  to the proven base policy (only refines ctx 1,2,7,8,38).
`resolve_option_card` (hand/deck by area/index) and `resolve_option_target` (in-play
active/bench) are the embedded helpers to decode an option; reuse them, don't reparse.

# Raging Bolt 0-30: diagnosis verdict (Pass 18 Part D)
Instrumenting the candidate's own `core_pilot_agent` and recording ONLY observed
option metadata (no fabricated effects) showed, vs Water:
- Raging Bolt **became active**, **attached correct Lightning(4)+Fighting(6)** onto it,
  **benched Ogerpon**, and **attacked** — and **never passed while an attack was offered**.
- Still went 0-4. So the failure is **deck/structural (loses the prize race vs the strong
  Water shell)**, NOT the hypothesized energy/tempo/pilot-fit gap.
- Only residual gap: **Crispin (1198) never played** — but that is a supporter *Play*,
  which Part F's hook guardrails explicitly forbid overriding ("no uncertain Play/Ability").

**Decision / Why:** Parts E (aggro playbook+fixtures), F (ctx-0 aggro attach/attack hook),
and the `league_raging_bolt_aggro_v1` candidate were **deliberately NOT built**. The
spec gated them on the diagnosis confirming an energy/tempo cause; it did not. The
attach/attack behaviors the hook would add are already happening, so the hook would be a
no-op fix for a non-existent problem. Family stays `candidate_for_future_probe` /
poor-fit, kept in the league via the original `league_raging_bolt_ogerpon`.
**How to apply:** If a future pass revisits Raging Bolt, target deck strength or a
*supporter-sequencing* (Crispin acceleration) capability — not energy color-matching,
which already works.
