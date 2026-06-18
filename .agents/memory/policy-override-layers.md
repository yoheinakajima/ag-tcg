---
name: Policy override layers (p5 scoring vs p6 decline)
description: How injected candidate policy layers work and why fixture decisions land in the embedded heuristic path
---

The experiments generator injects policy into a *copy* of root `main.py` (root is
immutable). Two distinct injection layers exist, with different powers:

- **p5 block** (`render_p5_block`, keyed by `p5_rules`): reassigns `_score_option`
  to add a board-aware delta (resolves option card id via (area,index), reads own
  active/bench ids + deckCount). It can only **re-weight** options — it cannot make
  the agent skip a prompt. So preferences that require *declining* (returning `[]`)
  are unreachable by p5 alone.
- **p6 block** (`render_p6_block`, keyed by `p6_rules`): wraps `_embedded_agent` so
  it returns `[]` when an own-observation decline rule fires **and `minCount == 0`**
  (empty selection legal). Two confirmed knobs only: `deckout_decline_threshold`
  (decline ctx==7 search when own deckCount<=thr) and `decline_mega_signal_no_snover`
  (decline ctx==7 when every option is Mega Abomasnow ex 723 and Snover 722 not on board).

**Why the layers decide fixture outcomes at all:** candidate `main.py`'s `agent()`
tries `_external_agent` (root `agent.py`) first, then falls through to the embedded
heuristic. Root `agent.py` reads only `select.get("options")` (**plural**), but
replay fixtures use `select.option` (**singular**), so the external agent returns
`[]` on every fixture → fall-through to the embedded heuristic, where p5/p6 take
effect.

**Why:** a recorded live observation may instead use `options` plural; if so the
external/package agent could short-circuit and bypass these overrides in real games.
That is a pre-existing concern, not something the fixture gate proves. State it as
uncertain rather than claiming the policies are guaranteed live.

**How to apply:** any new "skip/decline" behavior belongs in a p6 rule (needs
minCount==0); pure preference nudges belong in p5. A combo spec with no
`policy_refs` can still carry inline keyword `overrides` — `generate_combo_candidate`
merges the spec's own `overrides` in addition to referenced policy specs.
