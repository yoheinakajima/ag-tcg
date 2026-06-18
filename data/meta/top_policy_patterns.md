# Top Policy Patterns (meta engine backlog)

Replays analyzed: **5** (coverage: partial).

Preserved policy seams per strategy track:

- **Alakazam/Dunsparce Psychic setup-control** — policy seam: _missing-piece planner_
  - signals: low energy, high tutor density, Abra/Kadabra/Alakazam line, Dunsparce draw engine
- **Bellibolt/Kilowattrel Lightning ramp** — policy seam: _ramp plan and exact tutor target selection_
  - signals: electric ramp engine, Tadbulb/Bellibolt, Wattrel/Kilowattrel acceleration
- **Generic engine-deck pattern** — policy seam: _plan-state tracker + discard-protection for plan pieces_
  - signals: lower energy, high search/redundancy, plan-state tracking, bench-width setup
- **Chaos as engine-supported disruption** — policy seam: _payoff condition tied to an observable opponent signal_
  - signals: Froslass handCount / Durant deckCount / bench-bloat / status — visible signals only

## Per-replay early-policy fingerprints

- `data/meta_replays/meta_replay_summary.json` — track=unclassified (confidence low); coverage=partial
  - no steps array; early-game policy is unknown
- `data/meta_replays/pass10_eval_status.json` — track=unclassified (confidence low); coverage=partial
  - no steps array; early-game policy is unknown
- `data/meta_replays/replay_inbox_errors.json` — track=unclassified (confidence low); coverage=partial
  - no steps array; early-game policy is unknown
- `data/meta_replays/replay_processing_state.json` — track=unclassified (confidence low); coverage=partial
  - no steps array; early-game policy is unknown
- `data/meta_replays/replay_registry.json` — track=unclassified (confidence low); coverage=partial
  - no steps array; early-game policy is unknown

## Uncertainty

- Replays present but track matcher is a future-work hook; assignments are 'unclassified'.
- Card ids are never invented; unknown ids stay unknown.
- Four strategy tracks are preserved as the labelling vocabulary.
