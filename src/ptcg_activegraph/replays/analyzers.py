"""Turn a parsed :class:`KaggleReplay` into a structured, *honest* analysis.

The cabt observation schema (validated against episode 80374966, module
1.30.1):

* Each step is ``[seat0_record, seat1_record]``. A record carries
  ``observation`` (the prompt shown to that seat) and ``action`` (the option
  index list that seat chose for that prompt).
* ``observation.current`` holds the public board: ``players`` (each with
  ``active``/``bench``/``hand``/``discard``/``deckCount``/``handCount``/
  ``prize`` and the status booleans asleep/burned/confused/paralyzed/poisoned),
  plus ``stadium``, ``turn``, ``yourIndex``.
* ``observation.select`` is the decision prompt: ``context`` (what is being
  asked), ``type``, ``effect`` (the card whose effect is resolving, when any),
  ``deck`` (visible deck list for search prompts) and ``option`` (the legal
  choices). Each option references a card by ``(area, index)``:
    - area 1 -> deck   (resolve via ``select.deck[index].id``)
    - area 2 -> hand   (resolve via ``current.players[me].hand[index].id``)
  Board options carry ``inPlayArea``/``inPlayIndex``/``attackId`` instead.
* The chosen card(s) are ``select.option[i]`` for each ``i`` in ``action``.

Decision/option ``type`` ids on the main action menu (context 0):
    8  -> play card from hand        9  -> attach energy / evolve
    10 -> use ability                13 -> attack (carries attackId)
    14 -> pass / end turn            7  -> retreat / move
Within effect sub-prompts the option type is 3 ("pick this specific card").

Where an interpretation cannot be proven from the schema, the analysis records
an ``uncertain`` note rather than asserting a fabricated conclusion.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .kaggle_replay import KaggleReplay

# ---------------------------------------------------------------------------
# Card / context / option vocabulary (only ids we can name with confidence).
# ---------------------------------------------------------------------------

# Effect cards whose resolution the Pass-5 seams care about. Ids confirmed
# against data/cards/EN_Card_Data.csv (and data/cards/pass4_id_confirmation.json).
EFFECT_CARDS = {
    1121: "Ultra Ball",
    1092: "Secret Box",
    1145: "Mega Signal",
    1227: "Lillie's Determination",
    1219: "Team Rocket's Petrel",
    1262: "Surfing Beach",
}

# Setup-line Pokemon ids (the Snover -> Mega Abomasnow line + Kyogre attacker).
SNOVER = 722
MEGA_ABOMASNOW = 723
KYOGRE = 721
SETUP_POKEMON = {KYOGRE: "Kyogre", SNOVER: "Snover", MEGA_ABOMASNOW: "Mega Abomasnow ex"}

# Basic {W} Energy id (the deck's primary energy; safe discard fodder).
WATER_ENERGY = 3

# All named card ids used for readability in the analysis output.
CARD_NAMES = {**EFFECT_CARDS, **SETUP_POKEMON, WATER_ENERGY: "Basic {W} Energy"}

# Decision contexts we can name with confidence (others reported as-is).
CTX_DISCARD = 8          # choose card(s) from hand to discard (effect cost)
CTX_SEARCH_TO_HAND = 7   # choose card(s) from deck to take to hand (search)

# Option-type ids on the main action menu.
TYPE_NAMES = {
    3: "pick_card",
    7: "retreat_or_move",
    8: "play_from_hand",
    9: "attach_or_evolve",
    10: "ability",
    13: "attack",
    14: "pass_or_end",
}

# Zone area ids confirmed for card resolution.
AREA_DECK = 1
AREA_HAND = 2


def _name(card_id: Any) -> str:
    if card_id in CARD_NAMES:
        return f"{CARD_NAMES[card_id]} ({card_id})"
    return str(card_id)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _as_int_list(value: Any) -> list[int]:
    if not isinstance(value, (list, tuple)):
        return []
    return [v for v in value if isinstance(v, int) and not isinstance(v, bool)]


def _card_id(entry: Any) -> Any:
    if isinstance(entry, dict):
        v = entry.get("id")
        if isinstance(v, int) and not isinstance(v, bool):
            return v
    return None


def _zone_ids(zone: Any) -> list[int]:
    if not isinstance(zone, list):
        return []
    out: list[int] = []
    for e in zone:
        cid = _card_id(e)
        if cid is not None:
            out.append(cid)
    return out


def _my_player(obs: dict) -> dict | None:
    cur = obs.get("current") if isinstance(obs, dict) else None
    if not isinstance(cur, dict):
        return None
    me = cur.get("yourIndex")
    players = cur.get("players")
    if isinstance(players, list) and isinstance(me, int) and 0 <= me < len(players):
        p = players[me]
        return p if isinstance(p, dict) else None
    return None


def _board_pokemon_ids(player: dict | None) -> list[int]:
    """Active + bench Pokemon ids currently in play for a player."""
    if not isinstance(player, dict):
        return []
    ids: list[int] = []
    for slot in ("active", "bench"):
        ids.extend(_zone_ids(player.get(slot)))
    return ids


def _resolve_option_card(opt: dict, obs: dict, sel: dict) -> Any:
    """Resolve the card id an option refers to, or None if not resolvable."""
    if not isinstance(opt, dict):
        return None
    area = opt.get("area")
    index = opt.get("index")
    if not isinstance(index, int):
        return None
    if area == AREA_DECK:
        deck = sel.get("deck")
        ids = deck if isinstance(deck, list) else []
        if 0 <= index < len(ids):
            return _card_id(ids[index])
    elif area == AREA_HAND:
        player = _my_player(obs)
        hand = player.get("hand") if isinstance(player, dict) else None
        ids = hand if isinstance(hand, list) else []
        if 0 <= index < len(ids):
            return _card_id(ids[index])
    return None


# ---------------------------------------------------------------------------
# Episode + deck + final-state sections
# ---------------------------------------------------------------------------

def _analyze_episode(replay: KaggleReplay) -> dict:
    return {
        "episode_id": replay.episode_id,
        "name": replay.name,
        "module_version": replay.module_version,
        "schema_version": replay.schema_version,
        "rewards": replay.rewards,
        "statuses": replay.statuses,
        "act_timeout": replay.act_timeout,
        "run_timeout": replay.run_timeout,
        "episode_steps_cap": replay.episode_steps,
        "total_steps": replay.num_steps,
        "final_result": replay.final_result(),
        "agents": [a.get("Name") for a in replay.info.get("Agents", [])
                   if isinstance(a, dict)],
    }


def _load_baseline_counts() -> dict[str, dict[str, int]]:
    """Best-effort load of v1/v2 baseline deck composition for comparison."""
    import csv
    from pathlib import Path

    out: dict[str, dict[str, int]] = {}
    bases = {
        "v1": "data/baselines/v1_kaggle_349_8/deck.csv",
        "v2": "data/baselines/v2_kaggle_479_1_deck_energy_trim_light/deck.csv",
    }
    for label, path in bases.items():
        p = Path(path)
        if not p.exists():
            continue
        counts: dict[str, int] = {}
        try:
            with p.open(newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            for row in rows:
                if not row:
                    continue
                cell0 = row[0].strip()
                if not cell0 or not cell0.lstrip("-").isdigit():
                    continue  # header / non-numeric
                cid = cell0
                qty = 1
                if len(row) > 1 and row[1].strip().lstrip("-").isdigit():
                    qty = int(row[1].strip())
                counts[cid] = counts.get(cid, 0) + qty
            if counts:
                out[label] = counts
        except (OSError, ValueError):
            continue
    return out


def _analyze_decks(replay: KaggleReplay) -> dict:
    decks: dict[str, Any] = {"per_seat": [], "uncertain": []}
    submitted = replay.submitted_decks()
    if not submitted:
        decks["uncertain"].append(
            "no >=40-card deck action found in any step; cannot read submitted decks"
        )
        return decks
    baselines = _load_baseline_counts()
    for seat in sorted(submitted):
        ids = submitted[seat]
        counts = Counter(ids)
        seat_rec: dict[str, Any] = {
            "seat": seat,
            "card_count": len(ids),
            "unique_card_ids": sorted(counts),
            "counts": {str(k): v for k, v in sorted(counts.items())},
        }
        # Compare to baselines if we can.
        for label, base in baselines.items():
            seat_counts = {str(k): v for k, v in counts.items()}
            matches = seat_counts == base
            seat_rec[f"matches_{label}_baseline"] = matches
        decks["per_seat"].append(seat_rec)
    return decks


def _analyze_final_state(replay: KaggleReplay) -> dict:
    out: dict[str, Any] = {"per_seat": [], "uncertain": []}
    # The public board is symmetric; read it once from seat 0's final obs and
    # report both players from current.players.
    obs = replay.final_observation(0) or replay.final_observation(1)
    if not obs:
        out["uncertain"].append("no final observation with a board found")
        return out
    cur = obs.get("current", {})
    players = cur.get("players")
    if not isinstance(players, list):
        out["uncertain"].append("final observation has no players list")
        return out
    for seat, p in enumerate(players):
        if not isinstance(p, dict):
            continue
        prize = p.get("prize")
        prize_remaining = (
            sum(1 for x in prize if x is not None) if isinstance(prize, list) else None
        )
        out["per_seat"].append({
            "seat": seat,
            "deck_count": p.get("deckCount"),
            "hand_count": p.get("handCount"),
            "prize_slots": len(prize) if isinstance(prize, list) else None,
            "prize_remaining_facedown": prize_remaining,
            "active": _zone_ids(p.get("active")),
            "bench": _zone_ids(p.get("bench")),
            "discard_count": len(p.get("discard")) if isinstance(p.get("discard"), list) else None,
            "status_flags": {
                k: bool(p.get(k)) for k in
                ("asleep", "burned", "confused", "paralyzed", "poisoned")
            },
        })
    # Apparent loss reason: terminal rewards tell winner; deckCount==0 hints deckout.
    fr = replay.final_result()
    loser = None
    if fr.get("winner_seat") is not None:
        loser = 1 - fr["winner_seat"]
    reason = None
    if loser is not None and loser < len(out["per_seat"]):
        ldeck = out["per_seat"][loser].get("deck_count")
        if ldeck == 0:
            reason = f"seat {loser} likely lost to deck-out (final deckCount 0)"
        else:
            reason = (
                f"seat {loser} lost (reward); prizes/KO vs deckout not separable "
                f"from terminal state alone"
            )
    out["loser_seat"] = loser
    out["apparent_loss_reason"] = reason
    out["uncertain"].append(
        "win condition (prize-out vs deck-out vs no-bench) is inferred from final "
        "board + terminal rewards; the engine does not stamp an explicit reason"
    )
    return out


# ---------------------------------------------------------------------------
# Decision telemetry
# ---------------------------------------------------------------------------

def _iter_decisions(replay: KaggleReplay):
    """Yield (seat, step_index, obs, sel, options, action) for every prompt."""
    for seat in range(2):
        for step_idx, rec in enumerate(replay.agent_steps(seat)):
            obs = rec.get("observation")
            if not isinstance(obs, dict):
                continue
            sel = obs.get("select")
            if not isinstance(sel, dict):
                continue
            options = sel.get("option")
            if not isinstance(options, list) or not options:
                continue
            action = _as_int_list(rec.get("action"))
            yield seat, step_idx, obs, sel, options, action


def _analyze_telemetry(replay: KaggleReplay) -> dict:
    select_context = Counter()
    select_type = Counter()
    option_type = Counter()
    chosen_type = Counter()
    decisions = 0
    multi_option = 0
    first_legal = 0
    attack = play = attach_evolve = ability = end_pass = retreat = 0
    discard_contexts = 0
    search_contexts = 0
    effect_card_ids: Counter = Counter()

    for seat, step_idx, obs, sel, options, action in _iter_decisions(replay):
        decisions += 1
        ctx = sel.get("context")
        if ctx is not None:
            select_context[str(ctx)] += 1
        st = sel.get("type")
        if st is not None:
            select_type[str(st)] += 1
        if ctx == CTX_DISCARD:
            discard_contexts += 1
        elif ctx == CTX_SEARCH_TO_HAND:
            search_contexts += 1
        eff = sel.get("effect")
        if isinstance(eff, dict) and _card_id(eff) is not None:
            effect_card_ids[str(_card_id(eff))] += 1

        types = [o.get("type") if isinstance(o, dict) else None for o in options]
        for t in types:
            if t is not None:
                option_type[str(t)] += 1
        if len(options) > 1:
            multi_option += 1
            if action and action[0] == 0:
                first_legal += 1
        for idx in action:
            if 0 <= idx < len(types):
                t = types[idx]
                if t is not None:
                    chosen_type[str(t)] += 1
                if t == 13:
                    attack += 1
                elif t == 14:
                    end_pass += 1
                elif t == 10:
                    ability += 1
                elif t == 8:
                    play += 1
                elif t == 9:
                    attach_evolve += 1
                elif t == 7:
                    retreat += 1

    flr = round(first_legal / multi_option, 4) if multi_option else None
    return {
        "decisions": decisions,
        "select_context_distribution": dict(select_context),
        "select_type_distribution": dict(select_type),
        "option_type_distribution": dict(option_type),
        "chosen_option_type_distribution": dict(chosen_type),
        "attack_count": attack,
        "play_count": play,
        "attach_or_evolve_count": attach_evolve,
        "ability_count": ability,
        "end_or_pass_count": end_pass,
        "retreat_or_move_count": retreat,
        "discard_context_count": discard_contexts,
        "search_to_hand_context_count": search_contexts,
        "effect_card_ids_involved": dict(effect_card_ids),
        "multi_option_decisions": multi_option,
        "first_legal_pick_count": first_legal,
        "first_legal_pick_rate": flr,
        "type_name_legend": TYPE_NAMES,
        "context_legend": {
            str(CTX_DISCARD): "discard from hand",
            str(CTX_SEARCH_TO_HAND): "search/take to hand from deck",
        },
        "uncertain": [
            "attach vs evolve share option type 9 and are not separated here",
            "retreat and other board moves share option type 7",
        ],
    }


# ---------------------------------------------------------------------------
# Effect-resolution traces
# ---------------------------------------------------------------------------

def _heuristic_tag(effect_id: Any, ctx: Any, chosen_ids: list[int],
                   board_pokemon: list[int]) -> str:
    """good / bad / uncertain for a single effect-resolution decision."""
    # Discard decisions: discarding excess energy is good; discarding the only
    # setup Pokemon when none is in play is bad.
    if ctx == CTX_DISCARD:
        if not chosen_ids:
            return "uncertain"
        if all(c == WATER_ENERGY for c in chosen_ids):
            return "good"  # discarded only energy fodder
        for c in chosen_ids:
            if c in (SNOVER, MEGA_ABOMASNOW, KYOGRE) and c not in board_pokemon:
                return "bad"  # discarded a setup piece not on the board
        return "uncertain"
    # Search decisions: fetching the Snover line / a needed piece is good; we
    # cannot fully prove "optimal", so non-energy fetches are at best uncertain.
    if ctx == CTX_SEARCH_TO_HAND:
        if not chosen_ids:
            return "uncertain"
        if MEGA_ABOMASNOW in chosen_ids and SNOVER not in board_pokemon \
                and SNOVER not in chosen_ids:
            return "bad"  # fetched Mega without a Snover line
        return "uncertain"
    return "uncertain"


def _analyze_effect_traces(replay: KaggleReplay) -> dict:
    traces: list[dict] = []
    for seat, step_idx, obs, sel, options, action in _iter_decisions(replay):
        eff = sel.get("effect")
        eff_id = _card_id(eff) if isinstance(eff, dict) else None
        if eff_id is None:
            continue  # only trace decisions tied to a resolving effect card
        ctx = sel.get("context")
        player = _my_player(obs)
        board = _board_pokemon_ids(player)
        legal_ids = [_resolve_option_card(o, obs, sel) for o in options]
        legal_ids = [c for c in legal_ids if c is not None]
        chosen_ids = []
        for idx in action:
            if 0 <= idx < len(options):
                cid = _resolve_option_card(options[idx], obs, sel)
                if cid is not None:
                    chosen_ids.append(cid)
        pre = {
            "hand_count": player.get("handCount") if player else None,
            "deck_count": player.get("deckCount") if player else None,
            "board_pokemon": [_name(c) for c in board],
        }
        traces.append({
            "step": step_idx,
            "seat": seat,
            "effect_card": _name(eff_id),
            "effect_card_id": eff_id,
            "context": ctx,
            "context_name": {CTX_DISCARD: "discard", CTX_SEARCH_TO_HAND: "search_to_hand"}.get(ctx),
            "n_options": len(options),
            "legal_card_ids": [_name(c) for c in legal_ids],
            "chosen_card_ids": [_name(c) for c in chosen_ids],
            "chosen_raw_ids": chosen_ids,
            "pre_state": pre,
            "heuristic": _heuristic_tag(eff_id, ctx, chosen_ids, board),
        })
    by_card = Counter(t["effect_card_id"] for t in traces)
    return {
        "trace_count": len(traces),
        "traces_by_effect_card": {_name(k): v for k, v in by_card.items()},
        "traces": traces,
        "effect_cards_watched": {str(k): v for k, v in EFFECT_CARDS.items()},
        "uncertain": [
            "post-state hand/board after each effect is read from the *next* "
            "prompt where available; multi-card effects may interleave",
        ],
    }


# ---------------------------------------------------------------------------
# Failure-regime tags
# ---------------------------------------------------------------------------

def _failure_tags(replay: KaggleReplay, telemetry: dict, effects: dict,
                  final_state: dict) -> list[dict]:
    tags: list[dict] = []

    def add(tag: str, present: Any, confidence: str, evidence: str):
        tags.append({"tag": tag, "present": present,
                     "confidence": confidence, "evidence": evidence})

    traces = effects.get("traces", [])
    discard_traces = [t for t in traces if t.get("context") == CTX_DISCARD]
    search_traces = [t for t in traces if t.get("context") == CTX_SEARCH_TO_HAND]

    # searched_setup_piece_then_discarded
    searched = set()
    for t in search_traces:
        searched.update(t.get("chosen_raw_ids", []))
    discarded = set()
    for t in discard_traces:
        discarded.update(t.get("chosen_raw_ids", []))
    setup_search_then_discard = sorted(
        (searched & discarded) & set(SETUP_POKEMON)
    )
    add("searched_setup_piece_then_discarded",
        bool(setup_search_then_discard),
        "medium" if setup_search_then_discard else "low",
        (f"setup pieces both searched and later discarded: "
         f"{[_name(c) for c in setup_search_then_discard]}")
        if setup_search_then_discard else
        "no setup piece was both searched to hand and discarded")

    # discarded_last_or_only_snover
    snover_discards = [
        t for t in discard_traces
        if SNOVER in t.get("chosen_raw_ids", [])
        and "Snover (722)" not in t.get("pre_state", {}).get("board_pokemon", [])
    ]
    add("discarded_last_or_only_snover",
        bool(snover_discards),
        "medium" if snover_discards else "low",
        (f"Snover discarded with no Snover in play at step(s) "
         f"{[t['step'] for t in snover_discards]}")
        if snover_discards else "no Snover discarded while absent from board")

    # discarded_last_or_only_mega
    mega_discards = [t for t in discard_traces if MEGA_ABOMASNOW in t.get("chosen_raw_ids", [])]
    add("discarded_last_or_only_mega",
        bool(mega_discards),
        "low",
        (f"Mega Abomasnow discarded at step(s) {[t['step'] for t in mega_discards]}")
        if mega_discards else "no Mega Abomasnow discarded")

    # fetched_mega_without_snover_line
    bad_fetch = [t for t in search_traces if t.get("heuristic") == "bad"]
    add("fetched_mega_without_snover_line",
        bool(bad_fetch),
        "medium" if bad_fetch else "low",
        (f"Mega Abomasnow fetched without a Snover line at step(s) "
         f"{[t['step'] for t in bad_fetch]}")
        if bad_fetch else "no Mega fetch without Snover detected")

    # discarded_energy_ok (a positive tag — confirms safe discards happened)
    energy_ok = [t for t in discard_traces if t.get("heuristic") == "good"]
    add("discarded_energy_ok",
        bool(energy_ok),
        "high" if energy_ok else "low",
        (f"{len(energy_ok)} discard(s) hit only excess energy fodder")
        if energy_ok else "no clean energy-only discard observed")

    # overdraw_or_oversearch_near_deckout / chose_draw_when_deck_low
    low_deck_search = [
        t for t in search_traces
        if isinstance(t.get("pre_state", {}).get("deck_count"), int)
        and t["pre_state"]["deck_count"] <= 8
    ]
    add("overdraw_or_oversearch_near_deckout",
        bool(low_deck_search),
        "medium" if low_deck_search else "low",
        (f"search/draw effect used with deckCount<=8 at step(s) "
         f"{[(t['step'], t['pre_state']['deck_count']) for t in low_deck_search]}")
        if low_deck_search else "no search effect observed with a low deck")
    add("chose_draw_when_deck_low",
        bool(low_deck_search),
        "low",
        "shares evidence with overdraw_or_oversearch_near_deckout; exact draw "
        "vs search intent not separable")

    # effect_resolution_first_legal
    flr = telemetry.get("first_legal_pick_rate")
    if flr is None:
        add("effect_resolution_first_legal", None, "uncertain",
            "no multi-option decisions observed")
    else:
        add("effect_resolution_first_legal", flr >= 0.7,
            "high" if flr >= 0.85 else "medium",
            f"first-legal pick rate {flr} over "
            f"{telemetry.get('multi_option_decisions')} multi-option decisions")

    # played_stadium_when_already_stadium / played_secret_box_with_too_few_safe_discards
    add("played_stadium_when_already_stadium", None, "uncertain",
        "stadium re-play needs per-step stadium-owner diffing not yet implemented")
    add("played_secret_box_with_too_few_safe_discards", None, "uncertain",
        "Secret Box pre-play hand safety not separable from generic play prompts")

    # attach targeting (type 9 not split into active vs bench targets here)
    add("attached_to_current_attacker", None, "uncertain",
        "attach target (active vs bench) not resolved from board-area options yet")
    add("attached_to_non_attacker", None, "uncertain",
        "attach target (active vs bench) not resolved from board-area options yet")

    # timeout_safe
    statuses = [str(s) for s in replay.statuses]
    timed_out = any(s in ("TIMEOUT", "ERROR") for s in statuses)
    add("timeout_safe", not timed_out,
        "high" if statuses else "uncertain",
        f"terminal statuses = {statuses or 'unknown'}")

    # deckout_loss (this episode's loser)
    reason = final_state.get("apparent_loss_reason") or ""
    add("deckout_loss_for_loser", "deck-out" in reason,
        "medium" if "deck-out" in reason else "low",
        reason or "loss reason not inferable")

    return tags


# ---------------------------------------------------------------------------
# Top-level API
# ---------------------------------------------------------------------------

def analyze(replay: KaggleReplay) -> dict:
    """Produce the full structured analysis dict for a replay."""
    episode = _analyze_episode(replay)
    decks = _analyze_decks(replay)
    final_state = _analyze_final_state(replay)
    telemetry = _analyze_telemetry(replay)
    effects = _analyze_effect_traces(replay)
    tags = _failure_tags(replay, telemetry, effects, final_state)

    # Strongest (highest-confidence, present=True) failure tag for the summary.
    present = [t for t in tags if t.get("present") is True
              and t.get("tag") not in ("timeout_safe", "discarded_energy_ok")]
    order = {"high": 0, "medium": 1, "low": 2, "uncertain": 3}
    present.sort(key=lambda t: order.get(t.get("confidence"), 9))
    strongest = present[0]["tag"] if present else None

    return {
        "episode": episode,
        "decks": decks,
        "final_state": final_state,
        "telemetry": telemetry,
        "effect_traces": effects,
        "failure_tags": tags,
        "strongest_failure_tag": strongest,
        "source_path": replay.source_path,
    }


def to_markdown(analysis: dict) -> str:
    ep = analysis.get("episode", {})
    decks = analysis.get("decks", {})
    fs = analysis.get("final_state", {})
    tel = analysis.get("telemetry", {})
    eff = analysis.get("effect_traces", {})
    tags = analysis.get("failure_tags", [])

    lines = [
        f"# Replay analysis — episode {ep.get('episode_id')}",
        "",
        "## Episode",
        f"- name: {ep.get('name')}",
        f"- module version: {ep.get('module_version')}",
        f"- schema version: {ep.get('schema_version')}",
        f"- agents: {ep.get('agents')}",
        f"- statuses: {ep.get('statuses')}",
        f"- rewards: {ep.get('rewards')}",
        f"- final result: {ep.get('final_result')}",
        f"- total steps: {ep.get('total_steps')} (cap {ep.get('episode_steps_cap')})",
        f"- actTimeout: {ep.get('act_timeout')}  runTimeout: {ep.get('run_timeout')}",
        "",
        "## Decks (submitted)",
    ]
    for d in decks.get("per_seat", []):
        flags = [k for k in d if k.startswith("matches_") and d[k]]
        lines.append(
            f"- seat {d.get('seat')}: {d.get('card_count')} cards, "
            f"{len(d.get('unique_card_ids', []))} unique"
            + (f" — {', '.join(flags)}" if flags else "")
        )
    for u in decks.get("uncertain", []):
        lines.append(f"- _uncertain:_ {u}")

    lines += ["", "## Final state"]
    for s in fs.get("per_seat", []):
        lines.append(
            f"- seat {s.get('seat')}: deck={s.get('deck_count')} hand={s.get('hand_count')} "
            f"prizes_left={s.get('prize_remaining_facedown')} "
            f"active={s.get('active')} bench={s.get('bench')}"
        )
    lines.append(f"- apparent loss reason: {fs.get('apparent_loss_reason')}")

    lines += [
        "",
        "## Decision telemetry",
        f"- decisions: {tel.get('decisions')}",
        f"- select.context distribution: {tel.get('select_context_distribution')}",
        f"- select.type distribution: {tel.get('select_type_distribution')}",
        f"- option.type distribution: {tel.get('option_type_distribution')}",
        f"- chosen option.type distribution: {tel.get('chosen_option_type_distribution')}",
        f"- attack / play / attach-evolve / ability / end-pass / retreat: "
        f"{tel.get('attack_count')} / {tel.get('play_count')} / "
        f"{tel.get('attach_or_evolve_count')} / {tel.get('ability_count')} / "
        f"{tel.get('end_or_pass_count')} / {tel.get('retreat_or_move_count')}",
        f"- discard / search-to-hand contexts: "
        f"{tel.get('discard_context_count')} / {tel.get('search_to_hand_context_count')}",
        f"- effect card ids involved: {tel.get('effect_card_ids_involved')}",
        f"- first-legal pick rate: {tel.get('first_legal_pick_rate')}",
        "",
        "## Effect-resolution traces",
        f"- total traces: {eff.get('trace_count')}",
        f"- by effect card: {eff.get('traces_by_effect_card')}",
    ]
    for t in eff.get("traces", []):
        lines.append(
            f"  - step {t['step']} seat {t['seat']} **{t['effect_card']}** "
            f"[{t.get('context_name')}] chose {t['chosen_card_ids']} "
            f"from {t['n_options']} options "
            f"(deck={t['pre_state'].get('deck_count')}, "
            f"hand={t['pre_state'].get('hand_count')}) → _{t['heuristic']}_"
        )

    lines += ["", "## Failure / lesson tags"]
    for t in tags:
        lines.append(
            f"- **{t['tag']}**: present={t['present']} "
            f"(confidence={t['confidence']}) — {t['evidence']}"
        )
    lines += ["", f"**Strongest failure tag:** {analysis.get('strongest_failure_tag')}", ""]
    return "\n".join(lines)
