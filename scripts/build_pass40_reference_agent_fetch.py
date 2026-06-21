#!/usr/bin/env python3
"""Pass 40 (Part C) — fetch + materialize public reference agents.

For each registered public agent we run, READ-ONLY against Kaggle:
  * ``kaggle kernels output <ref>`` -> submission.tar.gz (the materialized agent),
  * ``kaggle kernels pull  <ref> -m`` -> source .ipynb + kernel-metadata.json,
then extract the tarball, verify it is the canonical cg_typed layout
({main.py, deck.csv, cg/{__init__,api,game,sim,utils}.py, cg/libcg.so}), copy the
agent code (main.py + deck.csv) into materialized/<id>/ (committed for inspection /
attribution), and copy the cg SDK once into the shared _sdk/cg (gitignored runtime).

Strictly READ-ONLY w.r.t. Kaggle: NO upload, NO submit, NO push. NO root/candidate
mutation, NO candidate generation. The kaggle client is imported lazily so the rest
of the test suite never depends on it.

Outputs data/experiments/pass40_reference_agent_fetch.{json,md}.
Env: requires KAGGLE_USERNAME / KAGGLE_KEY (already set in this shell).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"
REF = REPO / "data" / "reference_agents"

from ptcg_activegraph.tournament.artifacts import safe_extract_all  # noqa: E402
from ptcg_activegraph.reference_agents import (  # noqa: E402
    OPTIONAL_AGENTS, REFERENCE_AGENTS, REQUIRED_AGENTS,
)

CG_FILES = ["cg/__init__.py", "cg/api.py", "cg/game.py", "cg/sim.py",
            "cg/utils.py", "cg/libcg.so"]
EXPECTED_TOP = {"main.py", "deck.csv", "cg"}


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def _cg_signature(root: Path) -> str:
    """Stable hash over the cg SDK file set (sorted relpath + content)."""
    h = hashlib.sha256()
    for rel in CG_FILES:
        f = root / rel
        h.update(rel.encode())
        h.update(b"\0")
        h.update(f.read_bytes() if f.is_file() else b"<MISSING>")
        h.update(b"\0")
    return h.hexdigest()


def _materialize(api, spec) -> dict:
    raw_dir = REF / "raw_outputs" / spec.agent_id
    nb_dir = REF / "notebooks" / spec.agent_id
    mat_dir = REF / "materialized" / spec.agent_id
    rec: dict = {
        "agent_id": spec.agent_id, "kaggle_ref": spec.kaggle_ref,
        "optional": spec.optional, "ok": False, "errors": [],
    }
    raw_dir.mkdir(parents=True, exist_ok=True)
    nb_dir.mkdir(parents=True, exist_ok=True)
    mat_dir.mkdir(parents=True, exist_ok=True)

    # 1) source notebook + metadata (best-effort; provenance for Part D)
    try:
        api.kernels_pull(spec.kaggle_ref, path=str(nb_dir), metadata=True, quiet=True)
        meta = nb_dir / "kernel-metadata.json"
        if meta.is_file():
            rec["kernel_metadata"] = json.loads(meta.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        rec["errors"].append(f"kernels_pull: {exc}")

    # 2) kernel output -> submission.tar.gz (the materialized agent)
    try:
        api.kernels_output(spec.kaggle_ref, path=str(raw_dir), force=True, quiet=True)
    except Exception as exc:  # noqa: BLE001
        rec["errors"].append(f"kernels_output: {exc}")
        return rec

    tarball = raw_dir / "submission.tar.gz"
    if not tarball.is_file():
        rec["errors"].append("submission.tar.gz not present in kernel output")
        return rec
    rec["tarball_sha256"] = _sha256_file(tarball)
    rec["tarball_bytes"] = tarball.stat().st_size

    # 3) extract + verify layout
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        with tarfile.open(tarball, "r:gz") as tf:
            names = tf.getnames()
            safe_extract_all(tf, tdp)
        rec["tarball_entries"] = sorted(names)
        top = {n.split("/", 1)[0] for n in names if n}
        rec["top_level_ok"] = EXPECTED_TOP.issubset(top)
        missing = [rel for rel in CG_FILES if not (tdp / rel).is_file()]
        rec["cg_files_present"] = not missing
        if missing:
            rec["errors"].append(f"missing cg files: {missing}")

        main_py, deck_csv = tdp / "main.py", tdp / "deck.csv"
        if not main_py.is_file() or not deck_csv.is_file():
            rec["errors"].append("main.py/deck.csv missing in tarball")
            return rec

        # deck.csv must be exactly 60 integer rows
        rows = [ln.strip() for ln in deck_csv.read_text(encoding="utf-8").splitlines()
                if ln.strip()]
        deck_ok = len(rows) == 60 and all(r.lstrip("-").isdigit() for r in rows)
        rec["deck_rows"] = len(rows)
        rec["deck_60_ints"] = deck_ok

        # main.py must define agent() and import the cg SDK (cg_typed lane)
        src = main_py.read_text(encoding="utf-8")
        rec["main_defines_agent"] = "def agent(" in src
        rec["main_imports_cg"] = ("from cg" in src or "import cg" in src)

        # copy committed agent code
        shutil.copy2(main_py, mat_dir / "main.py")
        shutil.copy2(deck_csv, mat_dir / "deck.csv")
        rec["materialized"] = {
            "main_py": str((mat_dir / "main.py").relative_to(REPO)),
            "deck_csv": str((mat_dir / "deck.csv").relative_to(REPO)),
            "main_py_sha256": _sha256_file(mat_dir / "main.py"),
            "deck_csv_sha256": _sha256_file(mat_dir / "deck.csv"),
        }
        rec["cg_signature"] = _cg_signature(tdp)

        # stash a private extracted copy (with cg/) for Part F tarball build
        stash = REF / "tarballs" / "_extracted" / spec.agent_id
        if stash.exists():
            shutil.rmtree(stash)
        shutil.copytree(tdp, stash)

    rec["ok"] = bool(
        rec.get("top_level_ok") and rec.get("cg_files_present")
        and rec.get("deck_60_ints") and rec.get("main_defines_agent")
        and rec.get("main_imports_cg"))
    return rec


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    REF.mkdir(parents=True, exist_ok=True)

    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except Exception as exc:  # noqa: BLE001
        print(f"FATAL: kaggle client unavailable: {exc}", file=sys.stderr)
        return 2
    api = KaggleApi()
    api.authenticate()

    records = [_materialize(api, spec) for spec in REFERENCE_AGENTS]
    by_id = {r["agent_id"]: r for r in records}

    # consolidate shared cg SDK: all REQUIRED agents must share one identical SDK
    req_sigs = {by_id[a.agent_id].get("cg_signature") for a in REQUIRED_AGENTS
                if by_id[a.agent_id].get("ok")}
    req_sigs.discard(None)
    cg_shared = len(req_sigs) == 1
    shared_sig = next(iter(req_sigs)) if cg_shared else None
    sdk_dir = REF / "_sdk" / "cg"
    if cg_shared:
        # copy the cg/ from the first ok required agent's extracted stash
        for a in REQUIRED_AGENTS:
            r = by_id[a.agent_id]
            if r.get("ok"):
                srccg = REF / "tarballs" / "_extracted" / a.agent_id / "cg"
                if sdk_dir.exists():
                    shutil.rmtree(sdk_dir)
                shutil.copytree(srccg, sdk_dir)
                break

    n_required_ok = sum(1 for a in REQUIRED_AGENTS if by_id[a.agent_id]["ok"])
    n_optional_ok = sum(1 for a in OPTIONAL_AGENTS if by_id[a.agent_id]["ok"])
    n_materialized = sum(1 for r in records if r["ok"])
    fetch_ok = n_required_ok == len(REQUIRED_AGENTS)

    payload = {
        "pass": "40", "part": "C", "local_only": True, "no_upload": True,
        "upload_performed": False, "auto_submit": False, "github_push": False,
        "candidate_generation": False, "kaggle_read_only": True,
        "fetch_branch": "succeeds" if fetch_ok else "partial",
        "required_count": len(REQUIRED_AGENTS), "optional_count": len(OPTIONAL_AGENTS),
        "required_materialized": n_required_ok, "optional_materialized": n_optional_ok,
        "total_materialized": n_materialized,
        "cg_sdk_shared_across_required": cg_shared,
        "cg_sdk_signature": shared_sig,
        "cg_sdk_path": str(sdk_dir.relative_to(REPO)) if cg_shared else None,
        "agents": records,
    }
    (EXP / "pass40_reference_agent_fetch.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "n/a")

    md = [
        "# Pass 40 — Reference-agent fetch + materialize (Part C)", "",
        "> READ-ONLY Kaggle fetch. NO upload, NO submit, NO push, NO root/candidate "
        "mutation, NO candidate generation. Agents are benchmark opponents only.", "",
        f"- fetch branch: **{payload['fetch_branch']}**",
        f"- required materialized: **{n_required_ok}/{len(REQUIRED_AGENTS)}**, "
        f"optional: **{n_optional_ok}/{len(OPTIONAL_AGENTS)}**, "
        f"total: **{n_materialized}**",
        f"- cg SDK shared across required agents: **{yn(cg_shared)}** "
        f"(`{shared_sig[:16] + '…' if shared_sig else 'n/a'}`)", "",
        "| agent_id | ok | deck_60_ints | agent() | imports cg | cg files | "
        "tarball bytes |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in records:
        md.append(
            f"| `{r['agent_id']}`{' *(opt)*' if r['optional'] else ''} | "
            f"{yn(r['ok'])} | {yn(r.get('deck_60_ints'))} | "
            f"{yn(r.get('main_defines_agent'))} | {yn(r.get('main_imports_cg'))} | "
            f"{yn(r.get('cg_files_present'))} | {r.get('tarball_bytes', 'n/a')} |")
    errs = [(r["agent_id"], r["errors"]) for r in records if r["errors"]]
    if errs:
        md += ["", "## Errors / notes"]
        for aid, e in errs:
            md.append(f"- `{aid}`: {e}")
    (EXP / "pass40_reference_agent_fetch.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"fetch: branch={payload['fetch_branch']} required={n_required_ok}/"
          f"{len(REQUIRED_AGENTS)} optional={n_optional_ok}/{len(OPTIONAL_AGENTS)} "
          f"total={n_materialized} cg_shared={cg_shared}")
    return 0 if fetch_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
