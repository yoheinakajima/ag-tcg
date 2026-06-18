"""Observation telemetry helpers (corrected opponent-observability contract).

Pass 5 treated *all* opponent state as hidden. That was too conservative. The
cabt observation schema (verified against replay 80374966,
``steps[N][0].observation.current.players[i]``) exposes, for BOTH seats:

    active, bench, benchMax, deckCount, discard, handCount, prize,
    asleep, burned, confused, paralyzed, poisoned

What stays genuinely hidden for the *opponent* is only the *contents* of
face-down zones:

    * ``hand``  — opponent's ``hand`` is ``null`` while ``handCount`` is a real
      integer (own ``hand`` is a populated list).
    * ``deck``  — not present in the agent observation at all (only ``deckCount``).
    * ``prize`` — a list of ``null`` placeholders: the *count* is observable, the
      identities are not.

So opponent **counts, board (active/bench ids), discard, and status flags are
observable**; only opponent hand/deck/prize *contents* are hidden. This module
reads an observation and returns a flat, JSON-friendly view with explicit
uncertainty flags for any null / face-down entry. It never raises: missing or
malformed fields come back as ``None`` (or empty), never guessed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


def _ids_and_unknowns(slot) -> tuple[list[int], int]:
    """Extract integer card ids from a board slot (active/bench/discard).

    Returns ``(ids, unknown_count)``. Entries that are ``None`` or carry no
    integer ``id`` (face-down / unrevealed) are counted as unknown rather than
    invented.
    """
    ids: list[int] = []
    unknown = 0
    if not isinstance(slot, list):
        return ids, unknown
    for entry in slot:
        if isinstance(entry, dict):
            cid = entry.get("id")
            if isinstance(cid, int) and not isinstance(cid, bool):
                ids.append(cid)
            else:
                unknown += 1
        elif entry is None:
            unknown += 1
        else:
            unknown += 1
    return ids, unknown


def _int_or_none(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _status_flags(player: dict) -> dict:
    """Observable status conditions (booleans) for a player."""
    flags = {}
    for name in ("asleep", "burned", "confused", "paralyzed", "poisoned"):
        v = player.get(name)
        flags[name] = bool(v) if isinstance(v, bool) else None
    return flags


def _count_facedown(slot) -> int | None:
    """Count entries in a face-down zone (e.g. prize): count observable, ids not."""
    if not isinstance(slot, list):
        return None
    return len(slot)


@dataclass
class ObservationView:
    """A corrected, flattened view of one agent observation.

    ``own_*`` fields come from ``players[yourIndex]``; ``opp_*`` from the other
    seat. Every field is observable per the corrected contract EXCEPT the
    opponent's hand/deck/prize *contents*, which is reflected in the
    ``uncertainty`` block.
    """

    valid: bool = False
    your_index: int | None = None
    opp_index: int | None = None

    # --- own seat (fully observable) ---
    own_deck_count: int | None = None
    own_hand_count: int | None = None
    own_active_ids: list[int] = field(default_factory=list)
    own_bench_ids: list[int] = field(default_factory=list)
    own_bench_count: int | None = None
    own_discard_ids: list[int] = field(default_factory=list)
    own_prize_count: int | None = None
    own_status_flags: dict = field(default_factory=dict)

    # --- opponent seat (counts + board + status observable; contents hidden) ---
    opp_deck_count: int | None = None
    opp_hand_count: int | None = None
    opp_active_ids: list[int] = field(default_factory=list)
    opp_bench_ids: list[int] = field(default_factory=list)
    opp_bench_count: int | None = None
    opp_discard_ids: list[int] = field(default_factory=list)
    opp_prize_count: int | None = None
    opp_status_flags: dict = field(default_factory=dict)

    # --- explicit uncertainty for null / face-down entries ---
    uncertainty: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def read_observation(obs) -> ObservationView:
    """Read an agent observation into an :class:`ObservationView`.

    Never raises. If the observation does not contain a usable
    ``current.players`` structure, returns ``ObservationView(valid=False)``.
    """
    view = ObservationView()
    try:
        if not isinstance(obs, dict):
            return view
        cur = obs.get("current")
        if not isinstance(cur, dict):
            return view
        players = cur.get("players")
        me = cur.get("yourIndex")
        if not isinstance(players, list) or not isinstance(me, int):
            return view
        if not (0 <= me < len(players)):
            return view
        opp = 1 - me if len(players) == 2 else None
        mine = players[me]
        if not isinstance(mine, dict):
            return view

        view.valid = True
        view.your_index = me
        view.opp_index = opp

        # Own seat.
        view.own_deck_count = _int_or_none(mine.get("deckCount"))
        view.own_hand_count = _int_or_none(mine.get("handCount"))
        view.own_active_ids, own_active_unknown = _ids_and_unknowns(mine.get("active"))
        view.own_bench_ids, own_bench_unknown = _ids_and_unknowns(mine.get("bench"))
        view.own_bench_count = (
            len(mine["bench"]) if isinstance(mine.get("bench"), list) else None
        )
        view.own_discard_ids, _ = _ids_and_unknowns(mine.get("discard"))
        view.own_prize_count = _count_facedown(mine.get("prize"))
        view.own_status_flags = _status_flags(mine)

        unc = {
            "opp_present": opp is not None,
            "own_active_facedown": own_active_unknown,
            "own_bench_facedown": own_bench_unknown,
        }

        # Opponent seat (only if it exists and is a dict).
        if opp is not None and isinstance(players[opp], dict):
            other = players[opp]
            view.opp_deck_count = _int_or_none(other.get("deckCount"))
            view.opp_hand_count = _int_or_none(other.get("handCount"))
            view.opp_active_ids, opp_active_unknown = _ids_and_unknowns(other.get("active"))
            view.opp_bench_ids, opp_bench_unknown = _ids_and_unknowns(other.get("bench"))
            view.opp_bench_count = (
                len(other["bench"]) if isinstance(other.get("bench"), list) else None
            )
            view.opp_discard_ids, opp_discard_unknown = _ids_and_unknowns(other.get("discard"))
            view.opp_prize_count = _count_facedown(other.get("prize"))
            view.opp_status_flags = _status_flags(other)

            # The opponent's hand is a face-down zone: its COUNT is observable,
            # its CONTENTS are not. ``hand`` is null for the opponent.
            opp_hand = other.get("hand")
            unc.update({
                "opp_hand_contents_hidden": opp_hand is None or not isinstance(opp_hand, list),
                "opp_deck_contents_hidden": "deck" not in other or not isinstance(other.get("deck"), list),
                "opp_prize_contents_hidden": True,
                "opp_active_facedown": opp_active_unknown,
                "opp_bench_facedown": opp_bench_unknown,
                "opp_discard_facedown": opp_discard_unknown,
            })
        view.uncertainty = unc
    except Exception:
        return ObservationView(valid=False)
    return view


# Convenience accessors used by chaos policies (each tolerates a missing field).

def opp_hand_count(obs) -> int | None:
    """Opponent hand SIZE (observable). Used by hand-avalanche / four-card-lock."""
    return read_observation(obs).opp_hand_count


def opp_bench_count(obs) -> int | None:
    """Opponent bench SIZE (observable). Used by bench-bloat punisher."""
    return read_observation(obs).opp_bench_count


def opp_deck_count(obs) -> int | None:
    """Opponent deck COUNT (observable). Used by mill pressure."""
    return read_observation(obs).opp_deck_count


def opp_status_flags(obs) -> dict:
    """Opponent status conditions (observable). Used by status-lock."""
    return read_observation(obs).opp_status_flags
