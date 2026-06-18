#!/usr/bin/env python3
"""Hard pre-upload gate: prove a candidate tarball's OWN main.py returns a
60-card deck on the cabt deck-selection step.

This validates the *submitted artifact* in isolation — it extracts the tarball,
imports the extracted ``main.py`` (never the repo root ``main.py``), runs it with
its cwd set to the extracted directory, and asserts the agent returns exactly 60
integer card ids when the observation's ``current`` and ``select`` are both
``None`` (the cabt step-0 deck-selection shape). It also confirms the tarball
contains exactly ``main.py`` + ``deck.csv``, that ``deck.csv`` has 60 integer
rows, and that a malformed observation does not raise.

Exit code 0 on PASS, 1 on FAIL. Stdlib-only so it can gate uploads anywhere.

Usage:
    python scripts/validate_candidate_tarball.py PATH/TO/candidate.tar.gz
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tarfile
import tempfile
from pathlib import Path

# Deck-selection observations. The first two are the documented literal-null
# shape. The last two model the Kaggle production shape that actually broke the
# original candidate: an observation where "current"/"select" are NOT literal
# keys (a Struct returns None for them, but `"select" in obs` is False). A
# correctly-packaged candidate must return its 60-card deck for ALL of these —
# a brittle `"select" in obs` membership check returns [] for the key-absent
# ones, which is exactly the Kaggle pre-game failure this gate catches.
STEP0_SHAPES = [
    {"current": None, "select": None, "logs": [], "step": 0},
    {"current": None, "select": None, "logs": [], "remainingOverageTime": 60,
     "step": 0},
    {"logs": [], "step": 0},
    {"logs": [], "remainingOverageTime": 60, "step": 0},
]

# A normal mid-game-ish observation with no legal options — the agent must
# coerce this into a legal (possibly empty) selection without raising.
MALFORMED_SHAPES = [
    None,
    {},
    {"current": {"players": []}, "select": {"options": [], "minCount": 0,
                                            "maxCount": 0}},
    {"current": {}, "select": {"options": [{"area": 2, "index": 0}],
                               "minCount": 1, "maxCount": 1}},
]


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _read_deck_rows(path: Path) -> list[int]:
    rows: list[int] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        rows.append(int(s))  # raises ValueError on a non-int row
    return rows


def validate(tarball: str) -> int:
    tb = Path(tarball)
    if not tb.exists():
        return _fail(f"tarball not found: {tb}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        # 1. Extract.
        try:
            with tarfile.open(tb, "r:gz") as tar:
                file_members = [m for m in tar.getmembers() if m.isfile()]
                tar.extractall(tmp_dir)  # noqa: S202 (our own build artifact)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"could not extract tarball: {exc!r}")

        # 2. Exactly main.py + deck.csv at the top level.
        names = sorted(Path(m.name).name for m in file_members)
        depths = {len(Path(m.name).parts) for m in file_members}
        if names != ["deck.csv", "main.py"]:
            return _fail(f"tarball must contain exactly main.py + deck.csv, "
                         f"found {names}")
        if depths != {1}:
            return _fail("main.py and deck.csv must be at the tarball top level "
                         f"(found nested paths: "
                         f"{[m.name for m in file_members]})")

        main_path = tmp_dir / "main.py"
        deck_path = tmp_dir / "deck.csv"
        if not main_path.exists() or not deck_path.exists():
            return _fail("extracted tarball missing main.py or deck.csv")

        # 3. deck.csv has exactly 60 integer rows.
        try:
            deck_rows = _read_deck_rows(deck_path)
        except ValueError as exc:
            return _fail(f"deck.csv has a non-integer row: {exc}")
        if len(deck_rows) != 60:
            return _fail(f"deck.csv has {len(deck_rows)} rows, expected 60")

        # 4 + 5. Import extracted main.py with cwd set to the extracted dir.
        old_cwd = os.getcwd()
        added_path = str(tmp_dir)
        sys.path.insert(0, added_path)
        os.chdir(tmp_dir)
        mod = None
        try:
            try:
                spec = importlib.util.spec_from_file_location(
                    "candidate_under_test", main_path)
                mod = importlib.util.module_from_spec(spec)
                sys.modules["candidate_under_test"] = mod
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001
                return _fail(f"could not import extracted main.py: {exc!r}")

            if not hasattr(mod, "agent") or not callable(mod.agent):
                return _fail("extracted main.py has no callable agent()")

            # 6 + 7 + 8. Deck-selection step returns list[int] len 60 == deck.csv.
            for obs in STEP0_SHAPES:
                try:
                    result = mod.agent(obs)
                except Exception as exc:  # noqa: BLE001
                    return _fail(f"agent raised on deck-selection obs "
                                 f"{obs!r}: {exc!r}")
                if not isinstance(result, list):
                    return _fail(f"agent returned {type(result).__name__}, "
                                 f"expected list, on obs {obs!r}")
                if len(result) != 60:
                    return _fail(f"agent returned {len(result)} cards on the "
                                 f"deck-selection step, expected 60 (obs {obs!r})")
                if not all(isinstance(c, int) and not isinstance(c, bool)
                           for c in result):
                    return _fail("agent deck return contained non-int entries")
                if sorted(result) != sorted(deck_rows):
                    return _fail("agent deck return does not match deck.csv "
                                 "card multiset")

            # 9. Malformed / no-option observations must not raise.
            for obs in MALFORMED_SHAPES:
                try:
                    out = mod.agent(obs)
                except Exception as exc:  # noqa: BLE001
                    return _fail(f"agent raised on malformed obs {obs!r}: "
                                 f"{exc!r}")
                if not isinstance(out, list):
                    return _fail(f"agent returned non-list on malformed obs "
                                 f"{obs!r}: {type(out).__name__}")
        finally:
            os.chdir(old_cwd)
            if added_path in sys.path:
                sys.path.remove(added_path)
            sys.modules.pop("candidate_under_test", None)

    print(f"PASS: {tb.name} returns a 60-card deck on select=None/current=None")
    print(f"  deck rows: 60  unique: {len(set(deck_rows))}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tarball", help="path to candidate .tar.gz")
    args = parser.parse_args()
    return validate(args.tarball)


if __name__ == "__main__":
    raise SystemExit(main())
