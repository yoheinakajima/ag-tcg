"""Pass 46D — turn-planning primitives v0 (PURE / READ-ONLY / NEVER-RAISE).

Reusable building blocks that future candidate-generation passes can call to reason
about a single decision frame WITHOUT overclaiming. Every primitive:

* is **pure**: no Object Storage writes, no EventStore writes, no network I/O, no
  dependency on production state, no mutation of its inputs;
* **never raises**: malformed / missing / partial data yields a structured
  ``{"checkable": False, ...}`` / ``unknown`` result, never an exception;
* is **honest**: card identities are surfaced only when positively readable from the
  option/select schema; hidden opponent hand contents are never read or fabricated;
  exact damage, lethal availability, missed-KO, Boss/gust correctness, spread-placement
  correctness, and "best action" are ALWAYS marked unsupported (see
  :func:`unsupported_claims`);
* carries **no deck-specific card strategy** — only generic role classification.

It imports only the pure decoders :mod:`action_resolver` and :mod:`turn_planning`
(no production / lifecycle / generation / promotion / submission code, and no
public-reference policy code).

Accepted inputs (any primitive that takes a "frame"):
* a Pass-46C Kaggle-replay **seat object** ``{"observation": {...}, "action": ...}``;
* a raw **observation** dict ``{"current": {...}, "select": {...}, "logs": [...]}``;
* a bare **select** dict ``{"option"/"options": [...], "minCount": ..., ...}``;
* a :class:`turn_planning.DecisionFrame` (or its ``to_dict()``).
"""
from __future__ import annotations

import functools
from typing import Any, Callable, Optional

from . import turn_planning as tp
from .action_resolver import (
    OPTION_TYPE_CLASS,
    area_name,
    resolve_option,
)

# Re-exported so callers can branch on the same family vocabulary the extractor uses.
ACTION_FAMILIES: tuple[str, ...] = tp.ACTION_FAMILIES
UNSUPPORTED_CLAIMS: tuple[str, ...] = tp.UNSUPPORTED_CLAIMS
UNSUPPORTED_SENTINEL: str = tp.UNSUPPORTED_SENTINEL

# Coarse legal-option taxonomy: action_class -> top-level taxonomy bucket. This is a
# read-only labelling, never a recommendation.
OPTION_TAXONOMY: dict[str, str] = {
    "attach_energy": "resource",
    "play_from_hand": "develop",
    "play_in_play": "develop",
    "use_ability": "ability",
    "select_card": "selection",
    "move_energy": "reposition",
    "attack": "attack",
    "end_turn": "terminal",
    "effect_choice": "effect",
    "unknown": "unknown",
}


def _never_raise(default_factory: Callable[[], Any]) -> Callable:
    """Decorator: any exception inside the wrapped primitive returns a structured
    default (with an ``error`` note) instead of propagating."""
    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - never-raise contract
                out = default_factory()
                if isinstance(out, dict):
                    out.setdefault("checkable", False)
                    notes = out.setdefault("notes", [])
                    if isinstance(notes, list):
                        notes.append("primitive raised and was contained: %r" % (exc,))
                return out
        return wrapper
    return deco


# --------------------------------------------------------------- 1. safe_get
@_never_raise(lambda: None)
def safe_get(obj: Any, path: Any, default: Any = None) -> Any:
    """Walk ``obj`` along ``path`` (a dotted string, or a list/tuple of keys/indices),
    returning ``default`` on any missing key, wrong type, or out-of-range index.

    Reads dict keys, object attributes, and list/tuple indices. Never raises.
    """
    if path is None:
        return obj if obj is not None else default
    if isinstance(path, str):
        steps: list[Any] = [p for p in path.split(".") if p != ""]
    elif isinstance(path, (list, tuple)):
        steps = list(path)
    else:
        steps = [path]
    cur = obj
    for step in steps:
        if cur is None:
            return default
        if isinstance(cur, dict):
            if step in cur:
                cur = cur[step]
                continue
            return default
        if isinstance(cur, (list, tuple)):
            idx: Optional[int] = None
            if isinstance(step, int):
                idx = step
            elif isinstance(step, str) and (step.lstrip("-").isdigit()):
                idx = int(step)
            if idx is not None and -len(cur) <= idx < len(cur):
                cur = cur[idx]
                continue
            return default
        if hasattr(cur, step) if isinstance(step, str) else False:
            cur = getattr(cur, step)
            continue
        return default
    return cur if cur is not None else default


# ------------------------------------------------------------ frame coercion
def _is_decision_frame(obj: Any) -> bool:
    return hasattr(obj, "option_families") and hasattr(obj, "acting_player")


def _coerce_obs(frame: Any) -> dict[str, Any]:
    """Return ``{"current","select","logs","action","seat","is_decision_frame"}`` from
    any accepted frame shape. Missing pieces are ``None``; never raises."""
    out: dict[str, Any] = {"current": None, "select": None, "logs": None,
                           "action": None, "seat": None, "is_decision_frame": False}
    if frame is None:
        return out
    if _is_decision_frame(frame):
        out["is_decision_frame"] = True
        out["seat"] = getattr(frame, "acting_player", None)
        out["select"] = {
            "context": getattr(frame, "context", None),
            "type": getattr(frame, "select_type", None),
            "minCount": getattr(frame, "min_count", None),
            "maxCount": getattr(frame, "max_count", None),
        }
        return out
    if not isinstance(frame, dict):
        return out
    # Kaggle seat object: {"observation": {...}, "action": ...}
    if isinstance(frame.get("observation"), dict):
        obs = frame["observation"]
        out["current"] = obs.get("current")
        out["select"] = obs.get("select")
        out["logs"] = obs.get("logs")
        out["action"] = frame.get("action")
        return out
    # Raw observation dict.
    if "current" in frame or "select" in frame or "logs" in frame:
        out["current"] = frame.get("current")
        out["select"] = frame.get("select")
        out["logs"] = frame.get("logs")
        out["action"] = frame.get("action")
        return out
    # Bare select dict.
    if "option" in frame or "options" in frame or "minCount" in frame or "maxCount" in frame:
        out["select"] = frame
        return out
    return out


def _options(select: Any) -> list:
    if not isinstance(select, dict):
        return []
    opts = select.get("option")
    if opts is None:
        opts = select.get("options")
    return opts if isinstance(opts, list) else []


# ------------------------------------------------------- 2. normalize_option_type
@_never_raise(lambda: {"type_code": None, "type_name": "unknown",
                       "action_class": "unknown", "taxonomy": "unknown",
                       "checkable": False, "notes": []})
def normalize_option_type(option_or_type: Any) -> dict[str, Any]:
    """Normalise an option (dict) OR a bare ``type`` (int / numeric str / enum name)
    to a canonical ``{type_code, type_name, action_class, taxonomy}``.

    Unknown shapes resolve to ``action_class == "unknown"`` rather than a guess.
    """
    raw = option_or_type.get("type") if isinstance(option_or_type, dict) else option_or_type
    code: Optional[int] = None
    if isinstance(raw, bool):
        code = None  # bools are never valid type codes
    elif isinstance(raw, int):
        code = raw
    elif isinstance(raw, str):
        t = raw.strip()
        if t.isdigit():
            code = int(t)
        elif t in tp._NAME_TO_TYPE:
            code = tp._NAME_TO_TYPE[t]
        elif t.lower() in tp._NAME_TO_TYPE:
            code = tp._NAME_TO_TYPE[t.lower()]
    action_class = OPTION_TYPE_CLASS.get(code, "unknown") if code is not None else "unknown"
    return {
        "type_code": code,
        "type_name": action_class,
        "action_class": action_class,
        "taxonomy": OPTION_TAXONOMY.get(action_class, "unknown"),
        "checkable": action_class != "unknown",
        "notes": [] if action_class != "unknown" else ["type %r not positively mapped" % (raw,)],
    }


# ----------------------------------------------------- 3. normalize_select_context
@_never_raise(lambda: {"context": None, "select_type": None, "min_count": None,
                       "max_count": None, "n_options": 0, "is_choice": False,
                       "is_forced_single": None, "checkable": False, "notes": []})
def normalize_select_context(select: Any) -> dict[str, Any]:
    """Honest summary of a select window: context/type codes, min/max counts (preserved
    exactly), option count, and whether it is a real choice vs a forced single step."""
    if _is_decision_frame(select):
        n = getattr(select, "n_options", 0) or 0
        return {
            "context": getattr(select, "context", None),
            "select_type": getattr(select, "select_type", None),
            "min_count": getattr(select, "min_count", None),
            "max_count": getattr(select, "max_count", None),
            "n_options": n,
            "is_choice": n > 1,
            "is_forced_single": n <= 1,
            "checkable": True,
            "notes": ["counts read from DecisionFrame"],
        }
    co = _coerce_obs(select)
    sel = co["select"] if co["select"] is not None else select
    if not isinstance(sel, dict):
        return {"context": None, "select_type": None, "min_count": None,
                "max_count": None, "n_options": 0, "is_choice": False,
                "is_forced_single": None, "checkable": False,
                "notes": ["no select dict"]}
    n = len(_options(sel))
    min_c = sel.get("minCount")
    max_c = sel.get("maxCount")
    return {
        "context": sel.get("context"),
        "select_type": sel.get("type"),
        "min_count": min_c,
        "max_count": max_c,
        "n_options": n,
        "is_choice": n > 1,
        "is_forced_single": (n <= 1) if isinstance(n, int) else None,
        "checkable": True,
        "notes": [],
    }


# ------------------------------------------------------- 4. classify_option_family
@_never_raise(lambda: {"family": "unknown", "confidence": "unknown",
                       "action_class": "unknown", "taxonomy": "unknown",
                       "type_code": None, "checkable": False, "notes": []})
def classify_option_family(option: Any, *, select: Any = None, board: Any = None,
                           turn: Any = None) -> dict[str, Any]:
    """Classify a single raw option into a conservative turn-planning family.

    Builds on the pure :func:`action_resolver.resolve_option` +
    :func:`turn_planning.classify_action_family`. Anything not positively mappable
    returns ``family == "unknown"`` — never a guess. ``board`` may be a normalized
    snapshot from :func:`board_snapshot_from_frame` (used only for setup phase hints).
    """
    norm = normalize_option_type(option)
    opt = option if isinstance(option, dict) else {"type": norm["type_code"]}
    res = resolve_option(tp._normalize_option(opt), select=select if isinstance(select, dict) else None,
                         board=None)
    fam, conf, notes = tp.classify_action_family(
        res, select=select if isinstance(select, dict) else None,
        board=board if isinstance(board, dict) else None,
        turn=turn if isinstance(turn, int) else None)
    return {
        "family": fam,
        "confidence": conf,
        "action_class": res.action_class,
        "taxonomy": OPTION_TAXONOMY.get(res.action_class, "unknown"),
        "type_code": norm["type_code"],
        "checkable": fam != "unknown",
        "notes": list(notes),
    }


# ------------------------------------------------------- 6. visible_counts_by_zone
@_never_raise(lambda: {"hand_count": None, "deck_count": None, "prize_remaining": None,
                       "discard_count": None, "bench_count": None, "bench_max": None,
                       "active_present": None, "checkable": False})
def visible_counts_by_zone(player_block: Any) -> dict[str, Any]:
    """Honest per-zone visible counts for ONE player block. ``prize_remaining`` is the
    length of the remaining-prize list (6 == took zero). Hidden hand contents are never
    read — only ``hand_count``."""
    counts = tp._player_counts(player_block if isinstance(player_block, dict) else None)
    counts["checkable"] = isinstance(player_block, dict)
    return counts


# ------------------------------------------------------ 5. board_snapshot_from_frame
@_never_raise(lambda: {"turn": None, "acting_seat": None, "your_index": None,
                       "self": None, "opponent": None, "supporter_played": None,
                       "stadium_played": None, "energy_attached": None,
                       "retreated": None, "n_players": 0, "checkable": False,
                       "notes": []})
def board_snapshot_from_frame(frame: Any, *, seat: Optional[int] = None) -> dict[str, Any]:
    """Normalised, never-raising board snapshot for the acting seat (and opponent).

    Accepts any frame shape (see module docstring). Opponent block carries visible
    COUNTS only — never hidden hand contents. For a bare :class:`DecisionFrame`
    (which has no raw board) the counts are unavailable and reported as such."""
    co = _coerce_obs(frame)
    if co["is_decision_frame"]:
        sb = getattr(frame, "self_board", None)
        ob = getattr(frame, "opponent_board", None)
        return {
            "turn": getattr(frame, "turn", None),
            "acting_seat": getattr(frame, "acting_player", None),
            "your_index": getattr(frame, "your_index", None),
            "self": sb if isinstance(sb, dict) else None,
            "opponent": ob if isinstance(ob, dict) else None,
            "supporter_played": getattr(frame, "supporter_played", None),
            "stadium_played": getattr(frame, "stadium_played", None),
            "energy_attached": getattr(frame, "energy_attached", None),
            "retreated": None,
            "n_players": (1 if isinstance(sb, dict) else 0) + (1 if isinstance(ob, dict) else 0),
            "checkable": True,
            "notes": ["snapshot derived from a DecisionFrame (counts only)"],
        }
    current = co["current"]
    eff_seat = seat if seat is not None else co["seat"]
    if not isinstance(current, dict):
        return {"turn": None, "acting_seat": eff_seat, "your_index": None,
                "self": None, "opponent": None, "supporter_played": None,
                "stadium_played": None, "energy_attached": None, "retreated": None,
                "n_players": 0, "checkable": False, "notes": ["no current board"]}
    if eff_seat is None:
        yi = current.get("yourIndex")
        eff_seat = yi if isinstance(yi, int) else None
    players = current.get("players")
    players = players if isinstance(players, list) else []
    self_b = opp_b = None
    if isinstance(eff_seat, int) and 0 <= eff_seat < len(players):
        self_b = visible_counts_by_zone(players[eff_seat])
        if len(players) == 2:
            opp_b = visible_counts_by_zone(players[1 - eff_seat])
    return {
        "turn": current.get("turn"),
        "acting_seat": eff_seat,
        "your_index": current.get("yourIndex"),
        "self": self_b,
        "opponent": opp_b,
        "supporter_played": current.get("supporterPlayed"),
        "stadium_played": current.get("stadiumPlayed"),
        "energy_attached": current.get("energyAttached"),
        "retreated": current.get("retreated"),
        "n_players": len(players),
        "checkable": True,
        "notes": [],
    }


# ----------------------------------------------------- 7. legal_action_family_summary
@_never_raise(lambda: {"n_options": 0, "min_count": None, "max_count": None,
                       "families": {}, "families_present": [], "taxonomy_present": [],
                       "is_forced_single": None, "checkable": False, "notes": []})
def legal_action_family_summary(frame: Any, *, board: Any = None) -> dict[str, Any]:
    """Summarise the LEGAL option families present in a frame's select window.

    Preserves exact ``min_count`` / ``max_count`` and ``n_options``; classifies each
    option into a family (unknown when not mappable). This describes options PRESENTED,
    not which one was chosen (the selected action is not reliably recoverable from these
    traces — see Pass 46B/46C)."""
    if _is_decision_frame(frame):
        dfams: dict[str, int] = {}
        for fam in (getattr(frame, "option_families", None) or []):
            dfams[fam] = dfams.get(fam, 0) + 1
        n = getattr(frame, "n_options", 0) or 0
        return {
            "n_options": n,
            "min_count": getattr(frame, "min_count", None),
            "max_count": getattr(frame, "max_count", None),
            "families": dfams,
            "families_present": sorted(dfams),
            "taxonomy_present": [],
            "is_forced_single": n <= 1,
            "checkable": True,
            "notes": ["families read from DecisionFrame.option_families "
                      "(raw options unavailable -> taxonomy buckets omitted)"],
        }
    co = _coerce_obs(frame)
    sel = co["select"]
    ctx = normalize_select_context(sel)
    snap = board if isinstance(board, dict) else board_snapshot_from_frame(frame)
    turn = snap.get("turn") if isinstance(snap, dict) else None
    fams: dict[str, int] = {}
    tax: dict[str, int] = {}
    for opt in _options(sel):
        c = classify_option_family(opt, select=sel, board=snap, turn=turn)
        fams[c["family"]] = fams.get(c["family"], 0) + 1
        tax[c["taxonomy"]] = tax.get(c["taxonomy"], 0) + 1
    return {
        "n_options": ctx["n_options"],
        "min_count": ctx["min_count"],
        "max_count": ctx["max_count"],
        "families": fams,
        "families_present": sorted(fams),
        "taxonomy_present": sorted(tax),
        "is_forced_single": ctx["is_forced_single"],
        "checkable": ctx["checkable"],
        "notes": ["families describe options presented, not the chosen action"],
    }


# -------------------------------------------------------- 8. energy_attach_candidates
@_never_raise(lambda: [])
def energy_attach_candidates(frame: Any, *, board: Any = None) -> list[dict[str, Any]]:
    """List attach-energy options with their visible destination zone.

    Destination is read from the option's ``inPlayArea`` (``active`` / ``bench``); if
    absent it is reported ``unknown`` (never guessed). Returns ``[]`` when there are no
    attach options."""
    co = _coerce_obs(frame)
    sel = co["select"]
    out: list[dict[str, Any]] = []
    for i, opt in enumerate(_options(sel)):
        norm = normalize_option_type(opt)
        if norm["action_class"] != "attach_energy":
            continue
        dest = "unknown"
        bench_index = None
        if isinstance(opt, dict) and "inPlayArea" in opt:
            dest = area_name(opt.get("inPlayArea"))
            bench_index = opt.get("inPlayIndex")
        out.append({
            "option_index": i,
            "destination": dest,
            "bench_index": bench_index,
            "visible": dest in ("active", "bench"),
            "notes": [] if dest in ("active", "bench")
            else ["attach destination not in option schema"],
        })
    return out


# ------------------------------------------------------ 9. score_energy_attach_generic
@_never_raise(lambda: {"score": 0.0, "destination": "unknown", "deck_specific": False,
                       "checkable": False, "rationale": [], "unsupported": []})
def score_energy_attach_generic(candidate: Any, *, board: Any = None) -> dict[str, Any]:
    """A GENERIC, deck-agnostic ordering heuristic for an attach candidate.

    This is NOT a value-of-information / lethal / damage computation and carries NO
    deck-specific card knowledge: it only encodes the generic role preference "fuel the
    active attacker before developing the bench". Exact attach value remains unsupported.
    """
    dest = candidate.get("destination") if isinstance(candidate, dict) else "unknown"
    snap = board if isinstance(board, dict) else None
    self_b = snap.get("self") if isinstance(snap, dict) else None
    active_present = self_b.get("active_present") if isinstance(self_b, dict) else None
    score = 0.0
    rationale: list[str] = []
    if dest == "active":
        score = 1.0 if active_present is not False else 0.6
        rationale.append("generic: prioritise fuelling the active attacker")
    elif dest == "bench":
        score = 0.5
        rationale.append("generic: bench attach develops a future attacker")
    else:
        rationale.append("destination unknown -> neutral generic score")
    return {
        "score": score,
        "destination": dest,
        "deck_specific": False,
        "checkable": dest in ("active", "bench"),
        "rationale": rationale,
        "unsupported": ["exact_attach_value", "lethal_availability", "best_action"],
    }


# -------------------------------------------------------- 10. setup_candidate_summary
@_never_raise(lambda: {"is_setup": None, "n_options": 0, "active_candidates": [],
                       "bench_candidates": [], "checkable": False, "notes": []})
def setup_candidate_summary(frame: Any, *, board: Any = None) -> dict[str, Any]:
    """During the setup phase, list option indices that place a Pokémon to the active
    spot vs the bench. ``is_setup`` is inferred from turn (0/1) or an absent self-active;
    when not inferable it is ``None`` (not a guess)."""
    co = _coerce_obs(frame)
    sel = co["select"]
    snap = board if isinstance(board, dict) else board_snapshot_from_frame(frame)
    turn = snap.get("turn") if isinstance(snap, dict) else None
    self_b = snap.get("self") if isinstance(snap, dict) else None
    active_present = self_b.get("active_present") if isinstance(self_b, dict) else None
    is_setup: Optional[bool]
    if isinstance(turn, int):
        is_setup = turn in (0, 1) or active_present is False
    elif active_present is False:
        is_setup = True
    else:
        is_setup = None
    active_c: list[int] = []
    bench_c: list[int] = []
    for i, opt in enumerate(_options(sel)):
        c = classify_option_family(opt, select=sel, board=snap, turn=turn)
        if c["family"] == "setup_active":
            active_c.append(i)
        elif c["family"] == "setup_bench":
            bench_c.append(i)
    return {
        "is_setup": is_setup,
        "n_options": len(_options(sel)),
        "active_candidates": active_c,
        "bench_candidates": bench_c,
        "checkable": isinstance(sel, dict),
        "notes": ["setup phase inferred from turn/active presence"],
    }


# -------------------------------------------------------- 11. search_candidate_summary
@_never_raise(lambda: {"n_search_options": 0, "visible_card_ids": [],
                       "all_ids_visible": None, "checkable": False, "notes": []})
def search_candidate_summary(frame: Any) -> dict[str, Any]:
    """Summarise deck-search (select-from-deck) options, surfacing ONLY card ids that are
    positively resolvable from ``select.deck[index]`` — never inventing identities."""
    co = _coerce_obs(frame)
    sel = co["select"]
    n_search = 0
    ids: list[Any] = []
    n_unresolved = 0
    for opt in _options(sel):
        res = resolve_option(tp._normalize_option(opt if isinstance(opt, dict) else {}),
                             select=sel if isinstance(sel, dict) else None)
        # Treat as a search option when it selects a card from the deck.
        is_deck = res.source_area == "deck" or (isinstance(sel, dict) and sel.get("deck"))
        if res.action_class == "select_card" and is_deck:
            n_search += 1
            if res.card_id is not None:
                ids.append(res.card_id)
            else:
                n_unresolved += 1
    return {
        "n_search_options": n_search,
        "visible_card_ids": ids,
        "all_ids_visible": (n_unresolved == 0) if n_search else None,
        "checkable": isinstance(sel, dict),
        "notes": (["%d search ids not positionally resolvable -> omitted" % n_unresolved]
                  if n_unresolved else []),
    }


# ------------------------------------------------------- 12. discard_candidate_summary
@_never_raise(lambda: {"n_discard_options": 0, "visible_card_ids": [],
                       "all_ids_visible": None, "checkable": False, "notes": []})
def discard_candidate_summary(frame: Any) -> dict[str, Any]:
    """Summarise discard (select-from-discard) options, surfacing ONLY card ids that are
    positively resolvable — never inventing identities."""
    co = _coerce_obs(frame)
    sel = co["select"]
    n_disc = 0
    ids: list[Any] = []
    n_unresolved = 0
    for opt in _options(sel):
        res = resolve_option(tp._normalize_option(opt if isinstance(opt, dict) else {}),
                             select=sel if isinstance(sel, dict) else None)
        if res.action_class == "select_card" and res.source_area == "discard":
            n_disc += 1
            if res.card_id is not None:
                ids.append(res.card_id)
            else:
                n_unresolved += 1
    return {
        "n_discard_options": n_disc,
        "visible_card_ids": ids,
        "all_ids_visible": (n_unresolved == 0) if n_disc else None,
        "checkable": isinstance(sel, dict),
        "notes": (["%d discard ids not resolvable -> omitted" % n_unresolved]
                  if n_unresolved else []),
    }


# -------------------------------------------------------------- 13. unsupported_claims
def unsupported_claims() -> dict[str, str]:
    """The fixed set of claims these primitives REFUSE to infer from a bare trace.

    Includes the extractor's contract plus primitive-specific guards. Stable so callers
    and tests can assert the guarantees never silently shrink."""
    flags = dict(tp.unsupported_flags())
    flags["exact_attach_value"] = UNSUPPORTED_SENTINEL
    flags["chosen_action_recovery"] = UNSUPPORTED_SENTINEL
    return flags
