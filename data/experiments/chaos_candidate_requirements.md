# Pass 5 — Chaos Telemetry Candidate Requirements

Local-only research artifact. For each chaos archetype seam this records the telemetry it would need to *prove* the disruption worked, whether our seat can supply it, the confirmed core card ids, the policy requirements, the blocker, and the minimum metric needed to unblock it.

**Key finding (Pass 8 correction):** earlier passes wrongly concluded that *all* opponent-side telemetry was hidden. In fact our seat observes the opponent's PUBLIC board state. The decisive proof for every chaos seam is nonetheless *causal* — "did OUR disruption cause this?" — and that attribution (plus the opponent's hand *contents*) remains unavailable. So the seams are **partially_observable** at best and chaos stays a **research stream, not the next upload stream**.

### Available (corrected)

- opponent handCount
- opponent deckCount
- opponent bench count
- visible active/bench IDs
- status flags
- discard contents
- game logs

### Still missing / uncertain

- opponent hand contents
- causal attribution of chaos cards
- whether chaos helps opponent setup

**Conclusion:** Chaos remains a research stream, not the next upload stream.

Own-side telemetry recorded by the harness:

- `candidate_won`
- `context_counts`
- `deck_count_last`
- `discard_decisions`
- `low_deck_decisions`
- `max_bench_seen`
- `max_hand_seen`
- `min_deck_count`
- `search_decisions`
- `steps`

Opponent-side telemetry that IS observable (public board state):

- `game_logs`
- `opponent_active_id`
- `opponent_bench_ids`
- `opponent_bench_size`
- `opponent_deck_count`
- `opponent_discard_contents`
- `opponent_hand_size`
- `opponent_status_flags`

## `chaos.hand_avalanche_froslass`

- **Goal:** Keep the opponent's hand large, then scale Mega Froslass ex damage off that hand size.
- **Telemetry availability:** **blocked**
- **Required telemetry:** `opponent_hand_size` (opponent), `own_attack_damage_dealt` (own), `candidate_won` (own)
- **Opponent-side signals observable (public board state):** `opponent_hand_size`
- **Own-side proxies available:** `candidate_won`, `steps`
- **Policy requirements:** official_card_csv, chaos_decklist_confirmed
- **Confirmed core card ids:** 861 Mega Froslass ex (MATCH), 103 Snorunt (MATCH), 860 Snorunt (MATCH), 1223 Harlequin (MATCH), 1237 Lucian (MATCH), 1213 Judge (MATCH), 1103 Meddling Memo (MATCH), 1087 Hand Trimmer (MATCH), 1197 Xerosic’s Machinations (MISMATCH)
- **Blockers:**
  - opponent PUBLIC board state IS observable (Pass 8 correction), but only as counts/visible ids, not proof of causation: opponent_hand_size
  - own-side signals not recorded by the harness: own_attack_damage_dealt
  - some core card ids are not a clean MATCH against the official card table (see status field)
  - no full legal 60-card chaos decklist confirmed without inventing card ids (chaos_decklist_confirmed gate)
- **Minimum metric to unblock:** partial — opponent hand SIZE is observable from our seat, but our own per-attack damage dealt is not recorded, so the damage-vs-hand-size relationship cannot be measured directly.

## `chaos.bench_bloat_punisher`

- **Goal:** Crowd the opponent's bench with Accompanying Flute, then punish with bench-count-scaling attackers.
- **Telemetry availability:** **blocked**
- **Required telemetry:** `opponent_bench_size` (opponent), `own_attack_damage_dealt` (own), `candidate_won` (own)
- **Opponent-side signals observable (public board state):** `opponent_bench_size`
- **Own-side proxies available:** `candidate_won`, `steps`
- **Policy requirements:** official_card_csv, chaos_decklist_confirmed
- **Confirmed core card ids:** 1091 Accompanying Flute (MATCH), 615 Zoroark (MATCH), 430 Team Rocket's Hypno (MATCH), 79 Incineroar ex (MATCH), 95 Teal Mask Ogerpon (MATCH), 956 Zeraora (MATCH), 1059 Gengar (MATCH), 1187 Morty’s Conviction (MISMATCH), 1204 Lisia’s Appeal (MISMATCH)
- **Blockers:**
  - opponent PUBLIC board state IS observable (Pass 8 correction), but only as counts/visible ids, not proof of causation: opponent_bench_size
  - own-side signals not recorded by the harness: own_attack_damage_dealt
  - some core card ids are not a clean MATCH against the official card table (see status field)
  - no full legal 60-card chaos decklist confirmed without inventing card ids (chaos_decklist_confirmed gate)
- **Minimum metric to unblock:** partial — opponent bench SIZE is observable from our seat, but our own per-attack damage dealt is not recorded, so the damage-vs-bench-count relationship cannot be measured directly.

## `chaos.mill_resource_destruction`

- **Goal:** Disrupt the opponent's deck / hand / energy so a brittle bot loses pieces or decks out.
- **Telemetry availability:** **partially_observable**
- **Required telemetry:** `opponent_deck_count` (opponent), `opponent_hand_size` (opponent), `candidate_won` (own), `steps` (own)
- **Opponent-side signals observable (public board state):** `opponent_deck_count`, `opponent_hand_size`
- **Own-side proxies available:** `candidate_won`, `steps`, `min_deck_count`
- **Policy requirements:** official_card_csv, chaos_decklist_confirmed
- **Confirmed core card ids:** 198 Durant ex (MATCH), 58 Great Tusk (MATCH), 896 Mega Scrafty ex (MATCH), 881 Team Rocket's Diglett (MATCH), 440 Team Rocket's Larvitar (MATCH), 290 Tyranitar (MATCH), 1120 Crushing Hammer (MATCH), 1149 Energy Swatter (MATCH), 1087 Hand Trimmer (MATCH)
- **Blockers:**
  - opponent PUBLIC board state IS observable (Pass 8 correction), but only as counts/visible ids, not proof of causation: opponent_deck_count, opponent_hand_size
  - causal attribution unavailable: cannot prove our chaos play (not the opponent's own line) caused the observed board change, nor rule out that it helped them set up
  - no full legal 60-card chaos decklist confirmed without inventing card ids (chaos_decklist_confirmed gate)
- **Minimum metric to unblock:** partial — opponent deck count and hand SIZE are observable from our seat, so opponent deckout pressure CAN be tracked directly via the public count; only the causal share from our mill actions is unproven.

## `chaos.status_confusion_lock`

- **Goal:** Stack Confusion / Burn / Sleep + forced switching so the bot mis-sequences and loses turns.
- **Telemetry availability:** **blocked**
- **Required telemetry:** `opponent_status_flags` (opponent), `opponent_lost_turns` (opponent), `candidate_won` (own)
- **Opponent-side signals observable (public board state):** `opponent_status_flags`
- **Opponent-side signals still hidden/causal:** `opponent_lost_turns`
- **Own-side proxies available:** `candidate_won`, `steps`
- **Policy requirements:** official_card_csv, chaos_decklist_confirmed
- **Confirmed core card ids:** 1095 Dangerous Laser (MATCH), 1265 Dizzying Valley (MATCH), 813 Mismagius ex (MATCH), 1204 Lisia’s Appeal (MISMATCH), 861 Mega Froslass ex (MATCH), 968 Dachsbun ex (MATCH), 854 Dustox (MATCH), 1243 Perilous Jungle (MATCH)
- **Blockers:**
  - opponent PUBLIC board state IS observable (Pass 8 correction), but only as counts/visible ids, not proof of causation: opponent_status_flags
  - opponent hidden/causal telemetry still not available to our seat: opponent_lost_turns
  - some core card ids are not a clean MATCH against the official card table (see status field)
  - no full legal 60-card chaos decklist confirmed without inventing card ids (chaos_decklist_confirmed gate)
- **Minimum metric to unblock:** partial — opponent status flags are observable from our seat (public board), but opponent lost turns are not surfaced as a metric, so the lock's turn-denial effect can only be inferred indirectly.

## `chaos.vivillon_decidueye_four_card_lock`

- **Goal:** Use Vivillon / Judge to pin the opponent at exactly 4 cards, enabling Decidueye ex's reduced-cost attack.
- **Telemetry availability:** **blocked**
- **Required telemetry:** `opponent_hand_size` (opponent), `own_attack_enabled` (own), `candidate_won` (own)
- **Opponent-side signals observable (public board state):** `opponent_hand_size`
- **Own-side proxies available:** `candidate_won`, `steps`, `context_counts`
- **Policy requirements:** official_card_csv, chaos_decklist_confirmed
- **Confirmed core card ids:** 1017 Scatterbug (MATCH), 1018 Spewpa (MATCH), 1019 Vivillon (MATCH), 1020 Rowlet (MATCH), 1021 Dartrix (MATCH), 1022 Decidueye ex (MATCH), 1213 Judge (MATCH), 1261 Forest of Vitality (MATCH), 1231 Dawn (MATCH), 1225 Hilda (MATCH)
- **Blockers:**
  - opponent PUBLIC board state IS observable (Pass 8 correction), but only as counts/visible ids, not proof of causation: opponent_hand_size
  - own-side signals not recorded by the harness: own_attack_enabled
  - no full legal 60-card chaos decklist confirmed without inventing card ids (chaos_decklist_confirmed gate)
- **Minimum metric to unblock:** partial — the exact-4 opponent hand SIZE condition IS observable from our seat (public count), so the lock state can be confirmed; only whether our own attack was enabled by it is unrecorded.

