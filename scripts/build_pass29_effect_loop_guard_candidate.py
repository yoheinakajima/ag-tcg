#!/usr/bin/env python3
"""Pass 29 (Part J) — build the effect_loop_exit_guard_v1 micro-candidate.

ONLY runs because the Part F feasibility gate passed. Creates a NEW candidate by
copying the Mega Venusaur tank's pilot+deck and appending a stateful loop-exit
guard as the new last top-level callable. Does NOT touch root main.py/deck.csv or
any existing tarball. The new tarball is written immutably under candidates_pass29.

The guard fires ONLY under the exact stuck signature (repeating non-progressing
board at the ctx0 main-action head while the base re-activates an in-play action
and an end option is offered); under all other conditions it returns the base
policy's choice unchanged, so it is non-inert only on the loop.
"""
from __future__ import annotations

import hashlib
import shutil
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC_TAR = REPO / "data" / "submissions" / "candidates_pass27" / \
    "league_mega_venusaur_tank.tar.gz"
OUT_DIR = REPO / "data" / "submissions" / "candidates_pass29"
CAND_ID = "effect_loop_exit_guard_v1"
FEASIBILITY = REPO / "data" / "experiments" / "pass29_effect_loop_feasibility.json"

GUARD_BLOCK = '''

# === PASS29 EFFECT-LOOP EXIT GUARD v1 ===
# Breaks a non-progressing within-turn action loop. At the Main-action context
# (cabt select.context == 0) the generic pilot can repeatedly re-activate the
# same in-play action (Mega Venusaur ex line), which forces the engine into a
# ctx33 (move-energy) -> ctx21 (place-card) sub-loop that makes ZERO board
# progress and never terminates (observed ~979x/turn -> step cap). An explicit
# `end` option (raw type 12/14) is offered EVERY iteration but the base policy
# always declines it (in_play_action selected 1958/1958 at the loop head). This
# guard detects the stuck signature (a repeating, non-progressing board) and
# selects the legal `end` option to break out. It NEVER fires unless that exact
# signature repeats past a conservative threshold, so normal play is unchanged.
_ELG_THRESHOLD = 12
_ELG_STATE = {"sig": None, "count": 0}
_ELG_BASE_EMBEDDED = _embedded_agent


def _elg_progress_sig(obs):
    try:
        b = build_board(obs)
        if not isinstance(b, dict):
            return None
        active = b.get("active") or {}
        return (
            b.get("deck_count"),
            len(b.get("hand") or []),
            active.get("card_id") if isinstance(active, dict) else None,
            len(b.get("discard") or []),
            b.get("prize_count"),
        )
    except Exception:
        return None


def _elg_end_option_index(options):
    for i, o in enumerate(options):
        if isinstance(o, dict) and o.get("type") in (12, 14):
            return i
    return -1


def _elg_embedded(obs):
    base = _ELG_BASE_EMBEDDED(obs)
    try:
        sel = _get_select(obs)
        if not isinstance(sel, dict) or sel.get("context") != 0:
            return base
        options = _get_options(sel)
        if not options:
            return base
        mn, mx = _get_min_max_count(sel, len(options))
        if mn != 1 or mx != 1 or not (isinstance(base, list) and len(base) == 1):
            return base
        base_opt = options[base[0]] if 0 <= base[0] < len(options) else None
        base_type = base_opt.get("type") if isinstance(base_opt, dict) else None
        # Never override an attack or an already-chosen end/pass.
        if base_type in (12, 13, 14):
            _ELG_STATE["sig"] = None
            _ELG_STATE["count"] = 0
            return base
        sig = _elg_progress_sig(obs)
        if sig is None:
            return base
        if sig == _ELG_STATE["sig"]:
            _ELG_STATE["count"] += 1
        else:
            _ELG_STATE["sig"] = sig
            _ELG_STATE["count"] = 1
            return base
        if _ELG_STATE["count"] < _ELG_THRESHOLD:
            return base
        end_i = _elg_end_option_index(options)
        if end_i < 0:
            return base
        forced = _validate_action([end_i], len(options), mn, mx)
        if forced and len(forced) == 1:
            _ELG_STATE["sig"] = None
            _ELG_STATE["count"] = 0
            return forced
    except Exception:
        pass
    return base


_embedded_agent = _elg_embedded


def effect_loop_exit_guard_agent(obs_dict):
    return _cp_deck_safe_agent(obs_dict)
# === END PASS29 EFFECT-LOOP EXIT GUARD v1 ===
'''


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    feas = __import__("json").loads(FEASIBILITY.read_text())
    if not feas.get("gate_passes"):
        print("Part F gate did NOT pass; refusing to build candidate.")
        return 1

    work = OUT_DIR / CAND_ID
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    # Extract the source candidate.
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="elg_src_"))
    with tarfile.open(SRC_TAR) as tf:
        tf.extractall(tmp)
    src_main = next(tmp.rglob("main.py"))
    src_deck = next(tmp.rglob("deck.csv"))

    base_src = src_main.read_text(encoding="utf-8")
    if "core_pilot_agent" not in base_src or "_cp_deck_safe_agent" not in base_src:
        print("unexpected base pilot shape; aborting")
        return 1
    new_main = base_src + GUARD_BLOCK
    (work / "main.py").write_text(new_main, encoding="utf-8")
    shutil.copyfile(src_deck, work / "deck.csv")

    # Package immutably (do not overwrite an existing tarball).
    tar_path = OUT_DIR / f"{CAND_ID}.tar.gz"
    if tar_path.exists():
        print(f"tarball already exists (immutable): {tar_path}")
    else:
        with tarfile.open(tar_path, "w:gz") as tf:
            tf.add(work / "main.py", arcname="main.py")
            tf.add(work / "deck.csv", arcname="deck.csv")

    manifest = {
        "candidate_id": CAND_ID,
        "pass": "29", "part": "J",
        "kind": "runtime_pilot_hook",
        "built_because": "Part F feasibility gate passed (optional_loop_with_exit; "
                         "exit observable + selectable; pilot declines it)",
        "base_candidate": "league_mega_venusaur_tank",
        "deck_unchanged_vs_base": _sha(src_deck) == _sha(work / "deck.csv"),
        "entrypoint": "effect_loop_exit_guard_agent",
        "guard_threshold": 12,
        "fires_only_on": "repeating non-progressing board signature at ctx0 while "
                         "base re-activates a non-attack in_play action and an end "
                         "option is offered",
        "non_inert_only_on_loop": True,
        "no_upload": True, "local_only": True,
        "modifies_root_files": False,
        "modifies_existing_tarballs": False,
        "tarball": str(tar_path.relative_to(REPO)),
        "tarball_sha256": _sha(tar_path),
        "main_sha256": _sha(work / "main.py"),
    }
    (work / "manifest.json").write_text(
        __import__("json").dumps(manifest, indent=2), encoding="utf-8")
    print(f"built {CAND_ID}: deck_unchanged={manifest['deck_unchanged_vs_base']} "
          f"-> {tar_path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
