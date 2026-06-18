#!/usr/bin/env python3
"""Hard entrypoint invariant gate for a candidate tarball.

``kaggle_environments`` does NOT run a function named ``agent``. It compiles the
candidate ``main.py``, execs it in a fresh namespace, and runs the **last
callable** in that namespace's insertion order
(``kaggle_environments.agent.get_last_callable`` -> ``[v for v in env.values()
if callable(v)][-1]``). A candidate can therefore pass the deck-return tarball
validator (which calls ``mod.agent``) yet still ship a *different* last callable
that hijacks the real entrypoint and returns ``[]`` on the deck-selection step
-> ``INVALID`` on Kaggle.

This validator ratchets that invariant. It proves, for the exact submitted
tarball, that:

  1. The tarball contains exactly top-level ``main.py`` + ``deck.csv``.
  2. ``deck.csv`` has exactly 60 integer rows.
  3. There are no forbidden (non-stdlib, unconditional) imports.
  4. The module exposes a callable ``agent`` that returns 60 ids on the four
     deck-selection observation shapes (canonical null, key-absent, empty-ish,
     Struct-like) and never raises on malformed observations.
  5. Resolving the entrypoint the way kaggle does (last callable in exec order)
     yields a callable.
  6. That last callable returns the 60-card deck on every deck-selection shape.
  7. That last callable delegates gameplay observations safely (a legal,
     in-range, deduplicated index selection; never raises).
  8. (optional, ``--smoke``) one live cabt game does not INVALID/ERROR.

Exit code 0 on PASS, 1 on FAIL. Stdlib-only (the optional ``--smoke`` step uses
``kaggle_environments`` only when present and degrades to a skip otherwise).

Usage:
    python scripts/validate_candidate_entrypoint.py PATH/TO/candidate.tar.gz [--smoke]
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
import tarfile
import tempfile
from pathlib import Path

# Deck-selection observation shapes (same coverage as the tarball validator):
# canonical literal-null, key-absent (Struct-like), and empty-ish.
STEP0_SHAPES = [
    {"current": None, "select": None, "logs": [], "step": 0},
    {"current": None, "select": None, "logs": [], "remainingOverageTime": 60,
     "step": 0},
    {"logs": [], "step": 0},
    {"logs": [], "remainingOverageTime": 60, "step": 0},
]


class _Struct:
    """A Struct-like observation whose ``current``/``select`` are absent."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


STRUCT_STEP0 = _Struct(logs=[], step=0)

# A simple legal gameplay observation: one option, exactly one pick required.
GAMEPLAY_SHAPES = [
    {"current": {"players": [], "yourIndex": 0},
     "select": {"options": [{"type": 8, "area": 2, "index": 0}],
                "minCount": 1, "maxCount": 1, "context": 99}, "step": 4},
    {"current": {"players": [], "yourIndex": 0},
     "select": {"options": [{"type": 13, "area": 2, "index": 0, "attackId": 1},
                            {"type": 8, "area": 2, "index": 1}],
                "minCount": 1, "maxCount": 1, "context": 3}, "step": 6},
]

# Malformed observations must never raise.
MALFORMED_SHAPES = [
    None,
    {},
    {"current": {"players": []}, "select": {"options": [], "minCount": 0,
                                            "maxCount": 0}},
]

_STDLIB_OK = {
    "__future__", "os", "sys", "json", "csv", "math", "random", "collections",
    "itertools", "functools", "typing", "copy", "re", "io", "time", "heapq",
}


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _read_deck_rows(path: Path) -> list:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s:
            rows.append(int(s))
    return rows


def _guarded_import_ids(tree: ast.AST) -> set:
    """ids() of import nodes inside a try block (guarded optional imports)."""
    guarded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for stmt in ast.walk(node):
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    guarded.add(id(stmt))
    return guarded


def _check_imports(src: str) -> str | None:
    """Return an error string if an unconditional non-stdlib/relative import
    survives; ``None`` if clean. Guarded (try/except) optional imports allowed."""
    tree = ast.parse(src)
    guarded = _guarded_import_ids(tree)
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.ImportFrom):
            if node.level != 0:
                return f"relative import survived: {ast.dump(node)}"
            top = (node.module or "").split(".")[0]
            if top not in _STDLIB_OK:
                return f"non-stdlib import: {node.module}"
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in _STDLIB_OK:
                    return f"non-stdlib import: {a.name}"
    return None


def _exec_last_callable(src: str, main_path: Path):
    """Replicate kaggle_environments.agent.get_last_callable: compile+exec the
    source in a fresh namespace and return (env, last_callable, name)."""
    env: dict = {"__file__": str(main_path), "__name__": "candidate_main"}
    code = compile(src, str(main_path), "exec")
    exec(code, env)  # noqa: S102 (our own build artifact, sandboxed temp dir)
    callables = [(k, v) for k, v in env.items() if callable(v)]
    if not callables:
        return env, None, None
    name, fn = callables[-1]
    return env, fn, name


def _is_60_deck(result, deck_rows) -> str | None:
    if not isinstance(result, list):
        return f"returned {type(result).__name__}, expected list"
    if len(result) != 60:
        return f"returned {len(result)} cards, expected 60"
    if not all(isinstance(c, int) and not isinstance(c, bool) for c in result):
        return "deck return contained non-int entries"
    if sorted(result) != sorted(deck_rows):
        return "deck return does not match deck.csv multiset"
    return None


def _is_legal_selection(out, n_options, mn, mx) -> str | None:
    if not isinstance(out, list):
        return f"returned non-list: {type(out).__name__}"
    if not all(isinstance(i, int) and not isinstance(i, bool) for i in out):
        return "selection contained non-int indices"
    if len(set(out)) != len(out):
        return "selection contained duplicate indices"
    if any(i < 0 or i >= n_options for i in out):
        return f"selection out of range [0,{n_options}): {out}"
    if not (mn <= len(out) <= mx):
        return f"selection size {len(out)} outside [{mn},{mx}]"
    return None


def _smoke_one_game(tmp_dir: Path) -> str | None:
    """Optional: one live cabt game must not INVALID/ERROR. Returns error or
    None; returns a sentinel string starting with 'SKIP' when cabt absent."""
    try:
        from kaggle_environments import make  # type: ignore
    except Exception:
        return "SKIP: kaggle_environments unavailable"
    main_path = str(tmp_dir / "main.py")
    try:
        env = None
        for cfg in ({}, {"actTimeout": 30}):
            try:
                env = make("cabt", configuration=cfg)
                break
            except Exception:
                continue
        if env is None:
            return "SKIP: make('cabt') failed"
        env.run([main_path, main_path])
        for agent_state in env.state:
            status = agent_state.get("status")
            if status not in ("ACTIVE", "INACTIVE", "DONE"):
                return f"live smoke status={status}"
    except Exception as exc:  # noqa: BLE001
        return f"live smoke raised: {exc!r}"
    return None


def validate(tarball: str, smoke: bool = False) -> int:
    tb = Path(tarball)
    if not tb.exists():
        return _fail(f"tarball not found: {tb}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        try:
            with tarfile.open(tb, "r:gz") as tar:
                members = [m for m in tar.getmembers() if m.isfile()]
                tar.extractall(tmp_dir)  # noqa: S202
        except Exception as exc:  # noqa: BLE001
            return _fail(f"could not extract tarball: {exc!r}")

        # 1. exactly top-level main.py + deck.csv
        names = sorted(Path(m.name).name for m in members)
        depths = {len(Path(m.name).parts) for m in members}
        if names != ["deck.csv", "main.py"] or depths != {1}:
            return _fail(f"tarball must be exactly top-level main.py + deck.csv, "
                         f"found {[m.name for m in members]}")

        main_path = tmp_dir / "main.py"
        deck_path = tmp_dir / "deck.csv"

        # 2. deck.csv has 60 integer rows
        try:
            deck_rows = _read_deck_rows(deck_path)
        except ValueError as exc:
            return _fail(f"deck.csv has a non-integer row: {exc}")
        if len(deck_rows) != 60:
            return _fail(f"deck.csv has {len(deck_rows)} rows, expected 60")

        src = main_path.read_text(encoding="utf-8")

        # 3. no forbidden imports
        imp_err = _check_imports(src)
        if imp_err:
            return _fail(imp_err)

        old_cwd = os.getcwd()
        added = str(tmp_dir)
        sys.path.insert(0, added)
        os.chdir(tmp_dir)
        try:
            # exec like kaggle does
            try:
                env, last_fn, last_name = _exec_last_callable(src, main_path)
            except Exception as exc:  # noqa: BLE001
                return _fail(f"could not exec candidate main.py: {exc!r}")

            # 4. module-level agent() returns 60 ids on all deck-selection shapes
            agent = env.get("agent")
            if not callable(agent):
                return _fail("module has no callable agent()")
            for obs in STEP0_SHAPES + [STRUCT_STEP0]:
                try:
                    res = agent(obs)
                except Exception as exc:  # noqa: BLE001
                    return _fail(f"agent() raised on deck obs {obs!r}: {exc!r}")
                err = _is_60_deck(res, deck_rows)
                if err:
                    return _fail(f"agent() {err} on deck obs {obs!r}")

            # 5. last callable resolves
            if last_fn is None:
                return _fail("no top-level callable found (kaggle would error)")
            print(f"  last top-level callable: {last_name!r}")

            # 6. last callable returns the 60-card deck on every deck-selection
            for obs in STEP0_SHAPES + [STRUCT_STEP0]:
                try:
                    res = last_fn(obs)
                except Exception as exc:  # noqa: BLE001
                    return _fail(f"last callable {last_name!r} raised on deck obs "
                                 f"{obs!r}: {exc!r}")
                err = _is_60_deck(res, deck_rows)
                if err:
                    return _fail(f"last callable {last_name!r} {err} on deck obs "
                                 f"{obs!r} -> would INVALID on Kaggle")

            # 7. last callable delegates gameplay safely (legal index selection)
            for obs in GAMEPLAY_SHAPES:
                sel = obs["select"]
                n = len(sel["options"])
                mn, mx = sel["minCount"], sel["maxCount"]
                try:
                    out = last_fn(obs)
                except Exception as exc:  # noqa: BLE001
                    return _fail(f"last callable {last_name!r} raised on gameplay "
                                 f"obs {obs!r}: {exc!r}")
                err = _is_legal_selection(out, n, mn, mx)
                if err:
                    return _fail(f"last callable {last_name!r} {err} on gameplay "
                                 f"obs {obs!r}")
            for obs in MALFORMED_SHAPES:
                try:
                    out = last_fn(obs)
                except Exception as exc:  # noqa: BLE001
                    return _fail(f"last callable {last_name!r} raised on malformed "
                                 f"obs {obs!r}: {exc!r}")
                if not isinstance(out, list):
                    return _fail(f"last callable {last_name!r} returned non-list on "
                                 f"malformed obs {obs!r}")
        finally:
            os.chdir(old_cwd)
            if added in sys.path:
                sys.path.remove(added)

        # 8. optional live smoke
        if smoke:
            smoke_res = _smoke_one_game(tmp_dir)
            if smoke_res and smoke_res.startswith("SKIP"):
                print(f"  live smoke: {smoke_res}")
            elif smoke_res:
                return _fail(smoke_res)
            else:
                print("  live smoke: one cabt game completed (no INVALID/ERROR)")

    print(f"PASS: {tb.name} entrypoint invariant holds "
          f"(last callable returns 60 on deck-selection and legal indices on gameplay)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tarball", help="path to candidate .tar.gz")
    parser.add_argument("--smoke", action="store_true",
                        help="also run one live cabt game (skips if cabt absent)")
    args = parser.parse_args()
    return validate(args.tarball, smoke=args.smoke)


if __name__ == "__main__":
    raise SystemExit(main())
