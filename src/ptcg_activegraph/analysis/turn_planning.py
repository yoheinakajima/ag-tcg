"""Pass 46B — turn-planning diagnostic extractor (READ-ONLY, pure).

Decode CABT sidecar JSON and Kaggle-env replay JSON into honest, confidence-tagged
``DecisionFrame`` / ``TurnPlanSummary`` structures for turn-planning diagnosis.

Honesty contract (do NOT overclaim):
* Nothing is invented. Card identities, KOs, prizes and attacks are reported only
  when directly readable from option schema fields or corroborated by engine logs /
  observable count deltas.
* The following are ALWAYS marked unsupported unless a trusted Search API or exact
  attack outcome is supplied separately (this module never supplies them):
  lethal availability, exact damage, missed KO, Boss/gust target correctness,
  spread-placement correctness, hidden-hand contents, "best" action, and any
  counterfactual attack outcome.
* This module imports only the pure :mod:`action_resolver` decoder. It never imports
  production mutation / lifecycle / generation / promotion / submission code, never
  writes storage, and never performs network I/O.

Important data reality (Pass-46B): tournament sidecars (``data/tournament/games/
*.json.gz``) persist ``steps`` as an INTEGER COUNT plus outcome metadata only — they
contain NO decision frames. Full decision frames exist only in Kaggle-env replay JSON
(``data/replays/*.json``). The reader detects both and reports honestly which fields
are present rather than fabricating frames for outcome-only sidecars.
"""
from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable, Optional

from .action_resolver import (
    OPTION_TYPE_CLASS,
    Resolution,
    area_name,
    resolve_option,
)

# --- honesty: claims this module will never make from a bare trace --------------
UNSUPPORTED_CLAIMS: tuple[str, ...] = (
    "lethal_availability",
    "exact_damage",
    "missed_ko",
    "boss_gust_target_correctness",
    "spread_placement_correctness",
    "hidden_hand_contents",
    "best_action",
    "counterfactual_attack_outcome",
)

UNSUPPORTED_SENTINEL = "unsupported / not inferable from trace"

# Action families surfaced to turn-planning diagnosis. Conservative: anything we
# cannot positively map falls back to "unknown" rather than a guessed family.
ACTION_FAMILIES: tuple[str, ...] = (
    "setup_active",
    "setup_bench",
    "main_play",
    "attach",
    "evolve",
    "ability",
    "retreat",
    "attack",
    "search_to_hand",
    "discard",
    "switch_to_active",
    "end",
    "unknown",
)

# Trace format tags returned by :func:`detect_format`.
FMT_KAGGLE_REPLAY = "kaggle_replay"
FMT_CABT_SIDECAR_OUTCOME_ONLY = "cabt_sidecar_outcome_only"
FMT_CABT_SIDECAR_FRAMES = "cabt_sidecar_frames"
FMT_UNKNOWN = "unknown"


def unsupported_flags() -> dict[str, str]:
    """The fixed set of claims this module refuses to infer from a bare trace."""
    return {k: UNSUPPORTED_SENTINEL for k in UNSUPPORTED_CLAIMS}


# --------------------------------------------------------------------------- IO
def read_trace(path: str | Path) -> Any:
    """Read a trace file. Supports plain ``.json`` and gzipped ``.json.gz``.

    Pure read; raises on missing/corrupt input rather than guessing.
    """
    p = Path(path)
    if p.suffix == ".gz" or p.name.endswith(".json.gz"):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    with open(p, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def detect_format(obj: Any) -> str:
    """Classify a loaded trace object without mutating it.

    * ``kaggle_replay`` — ``steps`` is a list of per-seat lists carrying
      ``observation`` blocks (full decision frames available).
    * ``cabt_sidecar_frames`` — a tournament sidecar whose ``steps`` is a list of
      frame objects (decision frames available).
    * ``cabt_sidecar_outcome_only`` — a tournament sidecar whose ``steps`` is an
      integer COUNT (outcome metadata only; NO decision frames).
    * ``unknown`` — anything else.
    """
    if not isinstance(obj, dict):
        return FMT_UNKNOWN
    steps = obj.get("steps")
    if isinstance(steps, int):
        if "result" in obj or "candidate_a" in obj or "rewards" in obj:
            return FMT_CABT_SIDECAR_OUTCOME_ONLY
        return FMT_UNKNOWN
    if isinstance(steps, list) and steps:
        first = steps[0]
        # Kaggle env: steps[i] is a list of per-seat dicts each with 'observation'.
        if isinstance(first, list) and first and isinstance(first[0], dict) \
                and "observation" in first[0]:
            return FMT_KAGGLE_REPLAY
        # A sidecar that DID persist frame dicts.
        if isinstance(first, dict) and ("observation" in first or "select" in first):
            return FMT_CABT_SIDECAR_FRAMES
    return FMT_UNKNOWN


# ----------------------------------------------------- option type normalization
# Reverse of OPTION_TYPE_CLASS plus a couple of common aliases, so the extractor
# accepts BOTH integer enum forms (``type: 13``) and string enum forms
# (``type: "attack"`` / ``type: "13"``) without inventing semantics.
_NAME_TO_TYPE: dict[str, int] = {
    "effect_choice": 0, "select_card": 3, "move_energy": 6, "play_from_hand": 7,
    "attach_energy": 8, "use_ability": 9, "play_in_play": 10, "end_turn": 12,
    "attack": 13,
}


def _normalize_option(option: Any) -> Any:
    """Coerce a string ``type`` (numeric string or known enum name) to its int code.

    Unknown strings are left untouched (resolve to ``unknown`` honestly). Integer
    codes pass through unchanged.
    """
    if not isinstance(option, dict):
        return option
    t = option.get("type")
    if isinstance(t, str):
        nt: Optional[int] = None
        if t.isdigit():
            nt = int(t)
        elif t in _NAME_TO_TYPE:
            nt = _NAME_TO_TYPE[t]
        elif t.lower() in _NAME_TO_TYPE:
            nt = _NAME_TO_TYPE[t.lower()]
        if nt is not None:
            opt = dict(option)
            opt["type"] = nt
            return opt
    return option


# ----------------------------------------------------------------- board access
def _as_list(v: Any) -> list:
    return v if isinstance(v, list) else []


def _player_counts(player: Any) -> dict[str, Optional[int]]:
    """Honest per-player counts from an ``obs.current.players[seat]`` block.

    ``prize`` is a LIST of remaining prize cards, so ``len(prize)`` is prizes
    REMAINING (6 == took zero). Hidden hand contents are never read; only counts.
    """
    if not isinstance(player, dict):
        return {"hand_count": None, "deck_count": None, "prize_remaining": None,
                "discard_count": None, "bench_count": None, "bench_max": None,
                "active_present": None}
    active = player.get("active")
    active_present: Optional[bool]
    if isinstance(active, list):
        active_present = len(active) > 0
    elif active is None:
        active_present = False
    else:
        active_present = True
    hand_count = player.get("handCount")
    if hand_count is None and isinstance(player.get("hand"), list):
        hand_count = len(player["hand"])
    deck_count = player.get("deckCount")
    if deck_count is None and isinstance(player.get("deck"), list):
        deck_count = len(player["deck"])
    prize = player.get("prize")
    prize_remaining = len(prize) if isinstance(prize, list) else None
    discard = player.get("discard")
    discard_count = len(discard) if isinstance(discard, list) else None
    bench = player.get("bench")
    bench_count = len(bench) if isinstance(bench, list) else None
    return {
        "hand_count": hand_count,
        "deck_count": deck_count,
        "prize_remaining": prize_remaining,
        "discard_count": discard_count,
        "bench_count": bench_count,
        "bench_max": player.get("benchMax"),
        "active_present": active_present,
    }


def _board_summary(current: Any, seat: Optional[int]) -> dict[str, Any]:
    """Summarise both players' visible board from an ``obs.current`` block."""
    out: dict[str, Any] = {
        "turn": None, "your_index": None, "acting_seat": seat,
        "supporter_played": None, "stadium_played": None,
        "energy_attached": None, "retreated": None, "turn_action_count": None,
        "players": [], "self": None, "opponent": None,
    }
    if not isinstance(current, dict):
        return out
    out["turn"] = current.get("turn")
    out["your_index"] = current.get("yourIndex")
    out["supporter_played"] = current.get("supporterPlayed")
    out["stadium_played"] = current.get("stadiumPlayed")
    out["energy_attached"] = current.get("energyAttached")
    out["retreated"] = current.get("retreated")
    out["turn_action_count"] = current.get("turnActionCount")
    players = _as_list(current.get("players"))
    out["players"] = [_player_counts(p) for p in players]
    if seat is not None and 0 <= seat < len(out["players"]):
        out["self"] = out["players"][seat]
        opp = 1 - seat if len(out["players"]) == 2 else None
        if opp is not None and 0 <= opp < len(out["players"]):
            out["opponent"] = out["players"][opp]
    return out


# ------------------------------------------------------------- option families
def _select_options(select: dict) -> list:
    return _as_list(select.get("option") or select.get("options"))


def classify_action_family(res: Resolution, *, select: Optional[dict] = None,
                           board: Optional[dict] = None,
                           turn: Optional[int] = None) -> tuple[str, str, list[str]]:
    """Map a resolved option to a conservative turn-planning action family.

    Returns ``(family, confidence, notes)``. Confidence is one of
    ``direct_option`` / ``inferred_from_state`` / ``unknown``. Anything that cannot
    be positively mapped returns ``("unknown", "unknown", [...])`` — never a guess.
    """
    notes: list[str] = []
    cls = res.action_class
    setup_phase = (turn in (0, 1)) or (
        isinstance(board, dict)
        and isinstance(board.get("self"), dict)
        and board["self"].get("active_present") is False
    )
    if cls == "attack":
        return "attack", "direct_option", notes
    if cls == "attach_energy":
        return "attach", "direct_option", notes
    if cls == "use_ability":
        return "ability", "direct_option", notes
    if cls == "end_turn":
        return "end", "direct_option", notes
    if cls == "select_card":
        if res.source_area == "discard":
            return "discard", "direct_option", ["select from discard"]
        if res.source_area == "deck" or (isinstance(select, dict) and select.get("deck")):
            return "search_to_hand", "direct_option", ["select from deck"]
        return "unknown", "unknown", ["select_card: source zone not resolvable"]
    if cls == "play_from_hand":
        if setup_phase and res.target_area == "active":
            return "setup_active", "inferred_from_state", ["play to active during setup"]
        if setup_phase and res.target_area == "bench":
            return "setup_bench", "inferred_from_state", ["play to bench during setup"]
        return "main_play", "direct_option", notes
    if cls == "play_in_play":
        if setup_phase and res.target_area == "bench":
            return "setup_bench", "inferred_from_state", ["place to bench during setup"]
        # play_in_play onto an existing in-play mon is most often an evolve; mark
        # inferred and keep the ambiguity explicit.
        return "evolve", "inferred_from_state", ["play_in_play (evolve/place ambiguous)"]
    if cls == "move_energy":
        return "unknown", "unknown", ["move_energy: not mapped to retreat without log"]
    if cls == "effect_choice":
        return "unknown", "unknown", ["effect_choice carries no family by schema"]
    return "unknown", "unknown", ["unmapped option type %r" % res.raw_type]


def _retreat_in_logs(logs: list) -> bool:
    """A retreat/switch is observable when an active<->bench swap appears in logs."""
    saw_active_to_bench = saw_bench_to_active = False
    for lg in logs if isinstance(logs, list) else []:
        if not isinstance(lg, dict):
            continue
        f, t = area_name(lg.get("fromArea")), area_name(lg.get("toArea"))
        if f == "active" and t == "bench":
            saw_active_to_bench = True
        if f == "bench" and t == "active":
            saw_bench_to_active = True
    return saw_active_to_bench and saw_bench_to_active


# ----------------------------------------------------------------- data models
@dataclass
class DecisionFrame:
    game_id: Optional[str]
    source: Optional[str]
    step: Optional[int]
    turn: Optional[int]
    acting_player: Optional[int]
    your_index: Optional[int]
    context: Any = None
    select_type: Any = None
    min_count: Optional[int] = None
    max_count: Optional[int] = None
    n_options: int = 0
    selected_indices: list[int] = field(default_factory=list)
    selected_families: list[str] = field(default_factory=list)
    option_families: list[str] = field(default_factory=list)
    primary_family: str = "unknown"
    self_board: Any = None
    opponent_board: Any = None
    hand_count: Optional[int] = None
    deck_count: Optional[int] = None
    prize_remaining: Optional[int] = None
    discard_count: Optional[int] = None
    bench_count: Optional[int] = None
    supporter_played: Any = None
    stadium_played: Any = None
    energy_attached: Any = None
    observed_log_events: int = 0
    retreat_observed: bool = False
    legality_ok: Optional[bool] = None
    legality_notes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _legality(selected: list, n_options: int, min_c: Any, max_c: Any) -> tuple[Optional[bool], list[str]]:
    notes: list[str] = []
    k = len(selected)
    in_range: Optional[bool] = None
    if selected and n_options:
        in_range = all(isinstance(i, int) and 0 <= i < n_options for i in selected)
        if in_range is False:
            notes.append("selected index out of [0,%d)" % n_options)
    count_ok: Optional[bool] = None
    if isinstance(min_c, int) and isinstance(max_c, int):
        if selected:
            count_ok = (min_c <= k <= max_c)
            if not count_ok:
                notes.append("selected count %d outside [%s,%s]" % (k, min_c, max_c))
        elif min_c == 0:
            # zero picks are explicitly allowed -> an empty selection is legal.
            count_ok = True
        else:
            # Empty selection with minCount>0 is NOT flagged illegal: in real Kaggle
            # replays the per-seat `action` field does not always align with the
            # `select` shown in the same frame (the only local replay has many
            # ACTIVE frames with minCount>=1 yet an empty action), so an absent
            # selection is unverifiable here, not proof of an illegal play.
            notes.append("selection absent with minCount>0: legality not checkable "
                         "(action/select may not align in this trace)")
    if not selected and in_range is None and count_ok is None and not notes:
        notes.append("no selection recorded")
    if in_range is None and count_ok is None:
        return None, notes or ["legality not checkable (no option count / min-max)"]
    ok = bool(in_range is not False and count_ok is not False)
    return ok, notes


def build_decision_frame(*, game_id: Optional[str], source: Optional[str],
                         step: Optional[int], seat: Optional[int],
                         select: Optional[dict], action: Any,
                         current: Optional[dict], logs: Any) -> DecisionFrame:
    """Build one honest :class:`DecisionFrame` from raw replay components."""
    board = _board_summary(current, seat)
    turn = board.get("turn")
    options = _select_options(select) if isinstance(select, dict) else []
    n = len(options)
    resolved = [resolve_option(_normalize_option(o), select=select, board=None)
                for o in options]
    fams: list[str] = []
    for r in resolved:
        fam, _conf, _n = classify_action_family(r, select=select, board=board, turn=turn)
        fams.append(fam)
    selected = [i for i in (action or []) if isinstance(i, int)] if isinstance(action, list) else []
    sel_fams = sorted({fams[i] for i in selected if 0 <= i < len(fams)})
    logs_list = logs if isinstance(logs, list) else []
    retreat = _retreat_in_logs(logs_list)
    if retreat and "retreat" not in sel_fams:
        sel_fams = sorted(set(sel_fams) | {"retreat"})
    legality_ok, legality_notes = _legality(
        selected, n, select.get("minCount") if isinstance(select, dict) else None,
        select.get("maxCount") if isinstance(select, dict) else None)
    # primary family: prefer a selected non-"unknown" family, else most-specific.
    primary = "unknown"
    for fam in sel_fams:
        if fam != "unknown":
            primary = fam
            break
    self_b = board.get("self") or {}
    return DecisionFrame(
        game_id=game_id, source=source, step=step, turn=turn,
        acting_player=seat, your_index=board.get("your_index"),
        context=select.get("context") if isinstance(select, dict) else None,
        select_type=select.get("type") if isinstance(select, dict) else None,
        min_count=select.get("minCount") if isinstance(select, dict) else None,
        max_count=select.get("maxCount") if isinstance(select, dict) else None,
        n_options=n, selected_indices=selected, selected_families=sel_fams,
        option_families=fams, primary_family=primary,
        self_board=board.get("self"), opponent_board=board.get("opponent"),
        hand_count=self_b.get("hand_count"), deck_count=self_b.get("deck_count"),
        prize_remaining=self_b.get("prize_remaining"),
        discard_count=self_b.get("discard_count"),
        bench_count=self_b.get("bench_count"),
        supporter_played=board.get("supporter_played"),
        stadium_played=board.get("stadium_played"),
        energy_attached=board.get("energy_attached"),
        observed_log_events=len(logs_list), retreat_observed=retreat,
        legality_ok=legality_ok, legality_notes=legality_notes)


def iter_decision_frames(obj: Any, *, game_id: Optional[str] = None,
                         source: Optional[str] = None) -> list[DecisionFrame]:
    """Extract every decision frame (a seat presented a non-null ``select``).

    Returns ``[]`` for outcome-only sidecars (honestly — they carry no frames).
    """
    fmt = detect_format(obj)
    frames: list[DecisionFrame] = []
    if fmt == FMT_KAGGLE_REPLAY:
        gid = game_id or (obj.get("id") if isinstance(obj, dict) else None)
        steps = obj.get("steps") or []
        for i, step in enumerate(steps):
            if not isinstance(step, list):
                continue
            for seat, seat_obj in enumerate(step):
                if not isinstance(seat_obj, dict):
                    continue
                obs = seat_obj.get("observation") or {}
                select = obs.get("select")
                if not isinstance(select, dict):
                    continue
                frames.append(build_decision_frame(
                    game_id=gid, source=source or "kaggle_replay", step=i,
                    seat=seat, select=select, action=seat_obj.get("action"),
                    current=obs.get("current"), logs=obs.get("logs")))
        return frames
    if fmt == FMT_CABT_SIDECAR_FRAMES:
        gid = game_id or (obj.get("game_id") if isinstance(obj, dict) else None)
        for i, fr in enumerate(obj.get("steps") or []):
            if not isinstance(fr, dict):
                continue
            obs = fr.get("observation") or fr
            select = obs.get("select")
            if not isinstance(select, dict):
                continue
            frames.append(build_decision_frame(
                game_id=gid, source=source or "cabt_sidecar", step=i,
                seat=fr.get("seat"), select=select, action=fr.get("action"),
                current=obs.get("current"), logs=obs.get("logs")))
        return frames
    # outcome-only or unknown -> no frames
    return frames


# ------------------------------------------------------------ turn-level plan
@dataclass
class TurnPlanSummary:
    game_id: Optional[str]
    acting_player: Optional[int]
    n_frames: int = 0
    first_attack_turn: Optional[int] = None
    first_ko_turn: Optional[int] = None
    first_prize_turn: Optional[int] = None
    setup_bench_count: Optional[int] = None
    bench_occupancy_by_turn: dict[str, int] = field(default_factory=dict)
    energy_attachments_by_turn: dict[str, int] = field(default_factory=dict)
    turns_ending_without_attack: int = 0
    main_end_with_alternatives: int = 0
    search_action_count: int = 0
    search_card_ids: list[int] = field(default_factory=list)
    discard_action_count: int = 0
    discard_card_ids: list[int] = field(default_factory=list)
    retreat_switch_count: int = 0
    ability_use_count: int = 0
    hand_count_trajectory: list[Optional[int]] = field(default_factory=list)
    deck_count_trajectory: list[Optional[int]] = field(default_factory=list)
    dead_low_action_turns: int = 0
    invalid: bool = False
    timeout: bool = False
    error: bool = False
    unsupported: dict[str, str] = field(default_factory=unsupported_flags)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize_turn_plan(frames: list[DecisionFrame], *, acting_player: int,
                        game_id: Optional[str] = None,
                        prize_total: int = 6) -> TurnPlanSummary:
    """Aggregate per-(game, player) turn-planning features from decision frames.

    All turn-level claims are derived from observable counts / selected families /
    observable count deltas only. KO and prize timing are derived from prize-remaining
    deltas (logs-equivalent observable), never from inferred damage.
    """
    mine = [f for f in frames if f.acting_player == acting_player]
    s = TurnPlanSummary(game_id=game_id, acting_player=acting_player, n_frames=len(mine))
    if not mine:
        s.notes.append("no frames for this player")
        return s
    turns_seen: set[int] = set()
    turns_with_attack: set[int] = set()
    last_prize_remaining: Optional[int] = None
    for f in mine:
        t = f.turn
        if isinstance(t, int):
            turns_seen.add(t)
            occ_key = str(t)
            if isinstance(f.bench_count, int):
                prev = s.bench_occupancy_by_turn.get(occ_key)
                s.bench_occupancy_by_turn[occ_key] = max(prev, f.bench_count) \
                    if isinstance(prev, int) else f.bench_count
        s.hand_count_trajectory.append(f.hand_count)
        s.deck_count_trajectory.append(f.deck_count)
        fams = set(f.selected_families)
        if "attack" in fams:
            if isinstance(t, int):
                turns_with_attack.add(t)
                if s.first_attack_turn is None or t < s.first_attack_turn:
                    s.first_attack_turn = t
        if "attach" in fams and isinstance(t, int):
            k = str(t)
            s.energy_attachments_by_turn[k] = s.energy_attachments_by_turn.get(k, 0) + 1
        if "search_to_hand" in fams:
            s.search_action_count += 1
            for i in f.selected_indices:
                pass  # card ids only when positively resolvable (see below)
        if "discard" in fams:
            s.discard_action_count += 1
        if "ability" in fams:
            s.ability_use_count += 1
        if f.retreat_observed or "retreat" in fams or "switch_to_active" in fams:
            s.retreat_switch_count += 1
        if "end" in fams:
            # End selected while a non-end, non-unknown alternative existed.
            alt = {x for x in f.option_families if x not in ("end", "unknown")}
            if alt:
                s.main_end_with_alternatives += 1
        # dead/low-action: only a single legal option or only end/unknown available.
        productive = {x for x in f.option_families if x not in ("end", "unknown")}
        if f.n_options <= 1 or not productive:
            s.dead_low_action_turns += 1
        # KO / prize timing from prize-remaining deltas (observable, not inferred).
        opp = f.opponent_board if isinstance(f.opponent_board, dict) else None
        if opp is not None and isinstance(opp.get("prize_remaining"), int):
            pr = opp["prize_remaining"]
            if last_prize_remaining is not None and pr < last_prize_remaining:
                if s.first_prize_turn is None and isinstance(t, int):
                    s.first_prize_turn = t
                if s.first_ko_turn is None and isinstance(t, int):
                    s.first_ko_turn = t
                    s.notes.append("first_ko_turn approximated from opponent "
                                   "prize-remaining delta (KO-or-prize); exact KO "
                                   "event " + UNSUPPORTED_SENTINEL)
            last_prize_remaining = pr
        elif opp is not None and last_prize_remaining is None \
                and isinstance(opp.get("prize_remaining"), int):
            last_prize_remaining = opp["prize_remaining"]
    # turns that ended without an attack being chosen
    s.turns_ending_without_attack = len(turns_seen - turns_with_attack)
    # setup bench count: bench occupancy observed at the lowest seen turn
    if s.bench_occupancy_by_turn:
        lo = min(int(k) for k in s.bench_occupancy_by_turn)
        s.setup_bench_count = s.bench_occupancy_by_turn[str(lo)]
    return s


# --------------------------------------------------------- outcome-only sidecar
def sidecar_outcome(obj: Any) -> dict[str, Any]:
    """Honest outcome-level summary from an outcome-only tournament sidecar.

    Usable for win/loss/draw, game length (step count), seats, hard-failure flags —
    but NOT turn-planning (no frames). ``steps`` here is a COUNT.
    """
    if not isinstance(obj, dict):
        return {"ok": False, "reason": "not a dict"}
    return {
        "game_id": obj.get("game_id"),
        "candidate_a": obj.get("candidate_a"),
        "candidate_b": obj.get("candidate_b"),
        "result": obj.get("result"),
        "a_outcome": obj.get("a_outcome"),
        "rewards": obj.get("rewards"),
        "seat_assignment": obj.get("seat_assignment"),
        "statuses": obj.get("statuses"),
        "step_count": obj.get("steps") if isinstance(obj.get("steps"), int) else None,
        "elapsed_s": obj.get("elapsed_s"),
        "timeout": bool(obj.get("timeout")),
        "error": obj.get("error") is not None,
        "ok": bool(obj.get("ok")),
        "no_upload": obj.get("no_upload"),
        "frames_available": False,
    }
