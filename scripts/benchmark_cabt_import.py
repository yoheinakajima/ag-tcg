#!/usr/bin/env python3
"""Benchmark normal vs fast-stub cabt cold-start (Pass 7A, Part F).

Each measurement runs in a *fresh* subprocess because Python's import table is
process-global — you can only measure a cold ``import kaggle_environments`` once
per interpreter. Results are written to ``data/experiments/cabt_import_benchmark.json``.

This does NOT change any default behavior. The bulk runner keeps the safe
subprocess-per-game path until this benchmark validates the stub. Run from repo
root::

    python scripts/benchmark_cabt_import.py
    python scripts/benchmark_cabt_import.py --control data/baselines/v2_kaggle_479_1_deck_energy_trim_light
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import _bootstrap  # noqa: F401

OUT_PATH = Path("data/experiments/cabt_import_benchmark.json")

# A tiny program run in a fresh interpreter. ``mode`` and ``control`` are
# injected as a header (not via str.format) so literal ``{}`` braces are safe.
_CHILD = r"""
import json, sys, time
sys.path.insert(0, "src")
rec = {"mode": mode}
state_meta = None
if mode == "fast":
    from ptcg_activegraph.sim.kaggle_import_optimization import (
        enable_fast_cabt_import_stub,
    )
    t0 = time.time()
    state = enable_fast_cabt_import_stub(validate=False)
    import kaggle_environments  # noqa: F401
    rec["import_seconds"] = time.time() - t0
    state_meta = state.metadata()
else:
    t0 = time.time()
    import kaggle_environments  # noqa: F401
    rec["import_seconds"] = time.time() - t0

rec["import_ok"] = True
# one-game smoke + shape
try:
    from ptcg_activegraph.sim.kaggle_import_optimization import validate_fast_import
    t1 = time.time()
    v = validate_fast_import(control_dir=control)
    rec["smoke_seconds"] = time.time() - t1
    rec["validation"] = v
except Exception as exc:
    rec["smoke_error"] = repr(exc)
if state_meta is not None:
    rec["stub_metadata"] = state_meta
print("__BENCH__" + json.dumps(rec))
"""


def _run_mode(mode: str, control: str | None) -> dict:
    header = f"mode = {mode!r}\ncontrol = {control!r}\n"
    code = header + _CHILD
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=180,
    )
    wall = time.time() - t0
    rec: dict = {"mode": mode, "wall_seconds": wall}
    for line in proc.stdout.splitlines():
        if line.startswith("__BENCH__"):
            rec.update(json.loads(line[len("__BENCH__"):]))
            break
    else:
        rec["import_ok"] = False
        rec["error"] = (proc.stderr or proc.stdout or "no output")[-2000:]
    return rec


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Benchmark cabt import cold-start")
    p.add_argument("--control", default="data/baselines/v2_kaggle_479_1_deck_energy_trim_light")
    p.add_argument("--out", default=str(OUT_PATH))
    args = p.parse_args(argv)

    control = args.control if Path(args.control).exists() else None
    results = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "python": sys.version.split()[0],
        "control_dir": control,
        "normal": _run_mode("normal", control),
        "fast": _run_mode("fast", control),
    }

    n = results["normal"].get("import_seconds")
    f = results["fast"].get("import_seconds")
    if isinstance(n, (int, float)) and isinstance(f, (int, float)) and f > 0:
        results["import_speedup_x"] = round(n / f, 2)
    results["both_import_ok"] = bool(
        results["normal"].get("import_ok") and results["fast"].get("import_ok")
    )
    # The stub is only "validated" if BOTH a normal and fast smoke game ran AND
    # the fast validation reported ok. Without cabt installed this stays False.
    results["fast_validated"] = bool(
        results["fast"].get("validation", {}).get("ok")
        and results["normal"].get("validation", {}).get("ok")
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({
        "out": str(out),
        "normal_import_s": n,
        "fast_import_s": f,
        "speedup_x": results.get("import_speedup_x"),
        "fast_validated": results["fast_validated"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
