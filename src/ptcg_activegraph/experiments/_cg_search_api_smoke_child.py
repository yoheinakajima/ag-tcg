#!/usr/bin/env python3
"""Pass 40 (Part K) child — cg Search API import + one-step data smoke.

Run as a hard-timeout subprocess (native ``libcg.so`` must never be able to hang the
parent). Given an extracted reference agent dir (which bundles ``cg/`` + ``libcg.so``)
as argv[1], it:

  * imports ``cg`` / ``cg.api`` (loads ``libcg.so``);
  * introspects the search API surface (``search_begin/step/end/release``) WITHOUT
    starting any search (no MCTS, no torch, no game loop);
  * performs ONE safe data load (``all_card_data`` / ``all_attack``) to prove the SDK
    is live.

Prints a single JSON object to stdout. NEVER uploads / submits / mutates anything.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SEARCH_FNS = ["search_begin", "search_step", "search_end", "search_release"]
DATA_FNS = ["all_card_data", "all_attack", "to_observation_class"]
ENUMS = ["OptionType", "SelectType", "SelectContext", "CardType", "EnergyType"]


def main() -> int:
    out: dict = {"ok": False, "import_ok": False}
    try:
        ref_dir = Path(sys.argv[1]).resolve()
        os.chdir(ref_dir)
        sys.path.insert(0, str(ref_dir))
        import cg  # noqa: F401
        from cg import api  # type: ignore
        out["import_ok"] = True

        out["search_api"] = {
            fn: callable(getattr(api, fn, None)) for fn in SEARCH_FNS}
        out["data_api"] = {
            fn: callable(getattr(api, fn, None)) for fn in DATA_FNS}
        out["enums"] = {
            name: (getattr(api, name, None) is not None) for name in ENUMS}

        cards = api.all_card_data()
        attacks = api.all_attack()
        out["one_step_data"] = {
            "all_card_data_len": len(cards),
            "all_attack_len": len(attacks),
            "card_data_nonempty": len(cards) > 0,
            "attack_nonempty": len(attacks) > 0,
        }
        out["search_api_complete"] = all(out["search_api"].values())
        out["data_api_complete"] = all(out["data_api"].values())
        out["enums_complete"] = all(out["enums"].values())
        out["ok"] = (out["search_api_complete"] and out["data_api_complete"]
                     and out["enums_complete"] and out["one_step_data"][
                         "card_data_nonempty"])
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
