---
name: ActiveGraph live-control eval limits
description: What the offline ActiveGraph eval can and cannot measure for Pokémon-TCG pilot candidates
---

When evaluating Pokémon-TCG pilot candidates offline (surrogate pools, internal
league, focused eval), two limits are structural, not fixable by running more games:

1. **Surrogate ≠ Kaggle.** The weighted surrogate/self-play pool is directional only;
   small win-rate gaps between candidates are noise and must not be read as a real
   leaderboard edge. Calibrate against known references and report Wilson intervals.

2. **Deep board metrics are NOT measurable.** The cabt engine exposes board state as an
   opaque blob, so per-game rates like deckout / no-Pokémon-in-play / Mega-exposure /
   prize-liability cannot be extracted from eval logs — report them as NOT_MEASURED
   rather than fabricating numbers.

**How to apply:** the trustworthy evidence for whether a narrow hook actually changes
play is **decision-replay** over real attributed replays (count changed / on-seam /
illegal decisions and confirm positive-control preservation), not surrogate win-rates.
A hook that replays as changed=0 on the real seams is inert there regardless of any
surrogate win-rate wobble — keep the current control rather than promote it.
