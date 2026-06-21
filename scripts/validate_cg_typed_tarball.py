#!/usr/bin/env python3
"""cg_typed lane validator — a SEPARATE lane from the stdlib candidate gates.

Our own Kaggle candidates use the *stdlib* lane (scripts/validate_candidate_tarball.py
+ scripts/validate_candidate_entrypoint.py): exactly top-level ``main.py`` +
``deck.csv``, stdlib-only imports, exec'd in-process. Those gates are intentionally
strict and are NOT touched here.

Public reference / benchmark agents from the Pokémon-TCG competition are *cg_typed*:
they ship the ``cg`` SDK (``cg/{__init__,api,game,sim,utils}.py`` + native
``cg/libcg.so``) alongside ``main.py``/``deck.csv`` and ``import`` it. The stdlib
lane correctly REJECTS that shape (non-stdlib ``cg`` import, extra ``cg/`` tree).
This validator is the parallel lane for that shape. It NEVER runs on, gates, or
weakens our own submissions — it only describes/validates benchmark opponents.

Static (deterministic) contract — all required for ``ok``:
  1. Top-level entries are exactly ``main.py`` + ``deck.csv`` + ``cg/`` (no others).
  2. ``cg/`` contains ``__init__.py``, ``api.py``, ``game.py``, ``sim.py``,
     ``utils.py`` and the native ``libcg.so``.
  3. ``deck.csv`` has exactly 60 integer rows.
  4. ``main.py`` (by AST) imports the ``cg`` SDK — the defining trait of this lane.
  5. ``main.py`` (by AST) defines a top-level callable ``agent``.

Optional (``--import-smoke``): import the extracted ``main.py`` with ``cg`` on the
path in a HARD-TIMEOUT SUBPROCESS (native C can hang and cannot be interrupted in
process), and confirm a callable ``agent`` resolves. Recorded as pass/skip/fail; it
is NOT part of the static ``ok`` verdict (the native lib may be unavailable here).

Exit 0 on static PASS, 1 on static FAIL.

Usage:
    python scripts/validate_cg_typed_tarball.py PATH/TO/agent.tar.gz [--import-smoke]
"""
from __future__ import annotations

import argparse
import ast
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ptcg_activegraph.tournament.artifacts import safe_extract_all  # noqa: E402

CG_REQUIRED = ["cg/__init__.py", "cg/api.py", "cg/game.py", "cg/sim.py",
               "cg/utils.py", "cg/libcg.so"]
ALLOWED_TOP = {"main.py", "deck.csv", "cg"}

IMPORT_SMOKE_TIMEOUT_SECONDS = 60
_SMOKE_SNIPPET = (
    "import importlib.util,os,sys\n"
    "d=sys.argv[1]\n"
    "os.chdir(d); sys.path.insert(0,d)\n"
    "spec=importlib.util.spec_from_file_location('cg_agent_under_test',"
    "os.path.join(d,'main.py'))\n"
    "m=importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(m)\n"
    "ok=hasattr(m,'agent') and callable(getattr(m,'agent'))\n"
    "print('AGENT_OK' if ok else 'NO_AGENT')\n"
    "sys.exit(0 if ok else 3)\n"
)


def _read_deck_rows(path: Path) -> list[int]:
    rows: list[int] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s:
            rows.append(int(s))  # raises ValueError on non-int row
    return rows


def _imports_cg(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "cg":
                return True
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] == "cg":
                    return True
    return False


def _defines_agent(tree: ast.Module) -> bool:
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "agent" for n in tree.body)


def _last_top_level_callable(tree: ast.Module) -> str | None:
    last = None
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            last = n.name
        elif isinstance(n, ast.Assign):
            if isinstance(n.value, ast.Lambda) and n.targets:
                tgt = n.targets[0]
                if isinstance(tgt, ast.Name):
                    last = tgt.id
    return last


def _run_import_smoke(extract_dir: Path) -> dict:
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _SMOKE_SNIPPET, str(extract_dir)],
            capture_output=True, text=True,
            timeout=IMPORT_SMOKE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return {"result": "timeout",
                "detail": f">{IMPORT_SMOKE_TIMEOUT_SECONDS}s (native lib hang?)"}
    if proc.returncode == 0 and "AGENT_OK" in proc.stdout:
        return {"result": "pass", "detail": "imported; callable agent resolved"}
    tail = (proc.stderr.strip().splitlines() or ["<no stderr>"])[-3:]
    # A native/lib load failure here is environmental, not a tarball defect.
    return {"result": "skip_or_fail", "returncode": proc.returncode,
            "detail": " | ".join(tail)}


def inspect_cg_typed(tarball: str) -> dict:
    """Return a structured static analysis of a cg_typed tarball (no exec)."""
    tb = Path(tarball)
    res: dict = {"tarball": str(tb), "ok": False, "errors": []}
    if not tb.exists():
        res["errors"].append(f"tarball not found: {tb}")
        return res
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        try:
            with tarfile.open(tb, "r:gz") as tar:
                members = [m for m in tar.getmembers() if m.isfile()]
                safe_extract_all(tar, tmp_dir)
        except Exception as exc:  # noqa: BLE001
            res["errors"].append(f"could not extract: {exc!r}")
            return res

        names = [m.name for m in members]
        top = {n.split("/", 1)[0] for n in names if n}
        res["top_level"] = sorted(top)
        extra = sorted(top - ALLOWED_TOP)
        res["extra_top_level"] = extra
        if extra:
            res["errors"].append(f"unexpected top-level entries: {extra}")

        res["has_main"] = (tmp_dir / "main.py").is_file()
        res["has_deck"] = (tmp_dir / "deck.csv").is_file()
        res["has_cg_pkg"] = (tmp_dir / "cg").is_dir()
        missing_cg = [rel for rel in CG_REQUIRED if not (tmp_dir / rel).is_file()]
        res["cg_modules_present"] = not missing_cg
        res["libcg_present"] = (tmp_dir / "cg" / "libcg.so").is_file()
        if missing_cg:
            res["errors"].append(f"missing cg files: {missing_cg}")

        # deck.csv 60 ints
        if res["has_deck"]:
            try:
                rows = _read_deck_rows(tmp_dir / "deck.csv")
                res["deck_rows"] = len(rows)
                res["deck_60_ints"] = len(rows) == 60
                if len(rows) != 60:
                    res["errors"].append(f"deck.csv has {len(rows)} rows, expected 60")
            except ValueError as exc:
                res["deck_60_ints"] = False
                res["errors"].append(f"deck.csv non-integer row: {exc}")
        else:
            res["deck_60_ints"] = False
            res["errors"].append("deck.csv missing")

        # main.py AST
        if res["has_main"]:
            try:
                tree = ast.parse((tmp_dir / "main.py").read_text(encoding="utf-8"))
                res["imports_cg"] = _imports_cg(tree)
                res["defines_agent"] = _defines_agent(tree)
                res["last_top_level_callable"] = _last_top_level_callable(tree)
                if not res["imports_cg"]:
                    res["errors"].append("main.py does not import the cg SDK "
                                         "(not a cg_typed agent)")
                if not res["defines_agent"]:
                    res["errors"].append("main.py defines no top-level agent()")
            except SyntaxError as exc:
                res["imports_cg"] = res["defines_agent"] = False
                res["errors"].append(f"main.py syntax error: {exc}")
        else:
            res["imports_cg"] = res["defines_agent"] = False
            res["errors"].append("main.py missing")

        res["ok"] = bool(
            not extra and res.get("has_main") and res.get("has_deck")
            and res.get("has_cg_pkg") and res.get("cg_modules_present")
            and res.get("libcg_present") and res.get("deck_60_ints")
            and res.get("imports_cg") and res.get("defines_agent"))

        if res.get("_import_smoke_requested"):
            res["import_smoke"] = _run_import_smoke(tmp_dir)
    return res


def validate(tarball: str, import_smoke: bool = False) -> int:
    # inspect_cg_typed extracts to a temp dir that is torn down before it returns;
    # run the import-smoke inside the same extraction by toggling the flag.
    if import_smoke:
        tb = Path(tarball)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            with tarfile.open(tb, "r:gz") as tar:
                safe_extract_all(tar, tmp_dir)
            res = inspect_cg_typed(tarball)
            res["import_smoke"] = _run_import_smoke(tmp_dir)
    else:
        res = inspect_cg_typed(tarball)

    if res["ok"]:
        print(f"PASS (cg_typed): {Path(tarball).name} — main.py+deck.csv+cg/ SDK, "
              f"60-int deck, imports cg, defines agent()")
        if "import_smoke" in res:
            print(f"  import-smoke: {res['import_smoke']['result']} "
                  f"— {res['import_smoke'].get('detail','')}")
        return 0
    print(f"FAIL (cg_typed): {Path(tarball).name}")
    for e in res["errors"]:
        print(f"  - {e}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tarball", help="path to a cg_typed reference .tar.gz")
    ap.add_argument("--import-smoke", action="store_true",
                    help="also import main.py in a hard-timeout subprocess")
    args = ap.parse_args()
    return validate(args.tarball, import_smoke=args.import_smoke)


if __name__ == "__main__":
    raise SystemExit(main())
