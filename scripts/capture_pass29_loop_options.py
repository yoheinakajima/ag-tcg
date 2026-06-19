#!/usr/bin/env python3
"""Pass 29 observability ratchet — capture FULL per-option detail at the Venusaur
effect-loop contexts. LOCAL / READ-ONLY / NO UPLOAD.

The Pass-28 action trace only stored the SELECTED option's resolution, so we
could never see what the non-selected option at the ctx21 binary choice actually
is — i.e. whether option index 1 is a legal LOOP EXIT. This script re-runs the
one looping pairing (venusaur vs water) with a recorder that dumps the full raw
option list (and its resolution) for the loop contexts 33/21 and a small sample
of other contexts, then stops early once enough windows are captured.

No agent code is modified; root files are untouched; nothing is uploaded.

Output: data/experiments/pass29_loop_option_capture.json
"""
from __future__ import annotations

import json
import signal
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import run_pass28_forensic_trace as p28  # noqa: E402  (shared harness)

CAND = REPO / "data" / "submissions" / "candidates_pass27"
OUT = REPO / "data" / "experiments" / "pass29_loop_option_capture.json"

LOOP_CTX = {33, 21}
MAX_PER_CTX = 24          # plenty to characterise the repeated signature
GAME_TIMEOUT_S = 90


class _StopCapture(Exception):
    pass


def _raw_options(sel):
    return sel.get("option") or sel.get("options") or sel.get("choices") or []


def _make_capture_recorder(mod, candidate_id, family_id, sink: dict):
    entry = p28._entrypoint(mod)
    res = p28._resolver(mod)
    state = {"step": 0}

    def wrapped(obs, *args, **kwargs):
        action = entry(obs, *args, **kwargs)
        try:
            sel = obs.get("select") if isinstance(obs, dict) else None
            if isinstance(sel, dict):
                ctx = sel.get("context")
                opts = _raw_options(sel)
                if isinstance(opts, list) and opts and family_id == "venusaur":
                    bucket = sink.setdefault(ctx, [])
                    if len(bucket) < MAX_PER_CTX:
                        chosen = [i for i in (action or [])
                                  if isinstance(i, int) and 0 <= i < len(opts)]
                        bucket.append({
                            "step": state["step"],
                            "context": ctx,
                            "select_type": sel.get("type"),
                            "min_count": sel.get("minCount"),
                            "max_count": sel.get("maxCount"),
                            "n_options": len(opts),
                            "selected_indices": chosen,
                            "raw_options": [o if isinstance(o, dict) else {"_": repr(o)}
                                            for o in opts],
                            "resolved_options": [p28._resolve_option(obs, o, res)
                                                 for o in opts],
                            "board": p28._board_snapshot(obs, res),
                        })
                    # stop once both loop contexts are well sampled.
                    if all(len(sink.get(c, [])) >= MAX_PER_CTX for c in LOOP_CTX):
                        raise _StopCapture()
            state["step"] += 1
        except _StopCapture:
            raise
        except Exception:
            pass
        return action

    return wrapped


def _alarm(_s, _f):
    raise _StopCapture()


def main() -> int:
    from kaggle_environments import make

    modules = {}
    for fam, stem in (("venusaur", "league_mega_venusaur_tank"),
                      ("water", "league_water_core_reference")):
        d = CAND / stem
        main_py = d / "main.py"
        if not main_py.exists():
            # tarball-only: extract to a temp dir
            import tarfile
            import tempfile
            tmp = Path(tempfile.mkdtemp(prefix=f"p29_{fam}_"))
            with tarfile.open(CAND / f"{stem}.tar.gz") as tf:
                tf.extractall(tmp)
            main_py = next(tmp.rglob("main.py"))
        mod = p28._load_candidate_module(main_py)
        modules[fam] = (mod, stem)

    sink: dict = {}
    rec_v = _make_capture_recorder(modules["venusaur"][0],
                                   modules["venusaur"][1], "venusaur", sink)
    rec_w = _make_capture_recorder(modules["water"][0],
                                   modules["water"][1], "water", sink)

    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(GAME_TIMEOUT_S)
    captured = False
    for seat_specs in ([(rec_v, rec_w)], [(rec_w, rec_v)]):
        try:
            env = make("cabt")
            env.run(list(seat_specs[0]))
        except _StopCapture:
            captured = True
        except Exception as exc:  # noqa: BLE001
            print(f"game ended: {exc!r}")
        if all(len(sink.get(c, [])) >= 4 for c in LOOP_CTX):
            captured = True
            break
    signal.alarm(0)

    out = {
        "pass": "29", "purpose": "capture full per-option detail at venusaur loop "
        "contexts (33/21) to decode whether a legal exit option is observable",
        "no_upload": True, "local_only": True, "captured_stop_early": captured,
        "contexts_captured": {str(k): len(v) for k, v in sink.items()},
        "windows": sink,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"captured contexts: {out['contexts_captured']} -> {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
