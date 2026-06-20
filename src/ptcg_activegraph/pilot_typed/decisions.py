"""Per-context decision routing.

``decide(kind, board, options, profile, meta)`` is the single public entry the
fixtures grade AND the compiled runtime calls, so the deterministic gate tests
exactly what ships. Never raises; returns a small result dict per kind:

    setup_active / search_to_hand / emergency_backup_bench -> {"chosen_card_id": id|None}
    setup_bench_multi  -> {"chosen_card_ids": [id,...]}   (uses board["bench_pick_count"])
    discard            -> {"chosen_card_ids": [id,...]}   (uses board["discard_count"])
    draw_count         -> {"chosen_number": int|None}
    attach_energy      -> {"chosen_target_id": id|None}
    <unsupported kind> -> {"unsupported": True, "reason": str}

Each ``options`` element is a dict carrying at least ``card_id`` (for attach,
``card_id`` is the in-play target). The compiler builds these from the raw obs.
"""
from __future__ import annotations

from typing import Any

# STRIPPED by the compiler (embedded layer is flat); present so the lab package
# and fixtures import the real cross-module names.
from ptcg_activegraph.pilot_typed.tactics import (
    choose_attach_target, choose_discard, choose_emergency_bench,
    choose_search_target, choose_setup_active, choose_setup_bench,
    safe_draw_count,
)

_UNSUPPORTED_KINDS = {
    "attack": "attack damage/effect not in option schema (numeric attackId only)",
    "ko_target": "attack damage + target identity unsupported",
    "lethal": "depends on attack damage (unsupported)",
    "spread": "spread targets not exposed (Pass-28 honesty rule)",
    "boss": "Boss/gust target identity not observable",
    "gust": "gust target identity not observable",
}


def decide(kind: Any, board: Any, options: Any, profile: Any = None,
           meta: Any = None) -> dict:
    profile = profile if isinstance(profile, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    board = board if isinstance(board, dict) else {}
    options = options if isinstance(options, list) else []
    try:
        if kind in _UNSUPPORTED_KINDS:
            return {"unsupported": True, "reason": _UNSUPPORTED_KINDS[kind]}

        if kind == "setup_active":
            return {"chosen_card_id":
                    choose_setup_active(board, options, profile, meta)}  # noqa: F821

        if kind == "setup_bench_multi":
            need = board.get("bench_pick_count")
            if not (isinstance(need, int) and not isinstance(need, bool)):
                need = len(options)
            return {"chosen_card_ids":
                    choose_setup_bench(board, options, profile, meta, need)}  # noqa: F821

        if kind == "search_to_hand":
            return {"chosen_card_id":
                    choose_search_target(board, options, profile, meta)}  # noqa: F821

        if kind == "discard":
            need = board.get("discard_count")
            if not (isinstance(need, int) and not isinstance(need, bool)):
                need = 0
            return {"chosen_card_ids":
                    choose_discard(board, options, profile, meta, need)}  # noqa: F821

        if kind == "draw_count":
            numbers = [o.get("number") if isinstance(o, dict) else o
                       for o in options]
            return {"chosen_number":
                    safe_draw_count(board, numbers, profile)}  # noqa: F821

        if kind == "emergency_backup_bench":
            return {"chosen_card_id":
                    choose_emergency_bench(board, options, profile, meta)}  # noqa: F821

        if kind == "attach_energy":
            return {"chosen_target_id":
                    choose_attach_target(board, options, profile, meta)}  # noqa: F821
    except Exception:
        return {}
    return {}
