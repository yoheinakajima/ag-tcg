#!/usr/bin/env python3
"""Pass 40 (Part F) — immutable benchmark tarballs + reference_agent_manifest.

Assembles one deterministic, self-contained tarball per reference agent:

    <id>.tar.gz = { main.py, deck.csv, cg/{__init__,api,game,sim,utils}.py,
                    cg/libcg.so }

from the committed materialized code (materialized/<id>/main.py + deck.csv) and the
shared cg SDK (data/reference_agents/_sdk/cg). The tarball is the canonical runnable
unit benchmarked by Part G (smoke) and Part I (tick) — cg/ ships *alongside* main.py
so `import cg` and the cwd-relative `deck.csv` read both resolve.

Determinism: members are added in sorted order with mtime=0 / uid=gid=0 / fixed mode
into an UNCOMPRESSED tar (a fully reproducible `content_sha256`), then gzipped with
mtime=0 (a stable `tarball_sha256`). Re-running produces byte-identical artifacts.

The tarballs themselves stay gitignored (they bundle the gitignored libcg.so); the
committed manifest records their hashes so reproducibility is verifiable without
committing the binary. These are benchmark opponents only — NO Kaggle upload/submit,
NO promotion/mutation/queue, NO candidate generation, NO existing tarball touched.

Outputs:
  data/reference_agents/tarballs/<id>.tar.gz                 (gitignored)
  data/reference_agents/reference_agent_manifest.{json,md}   (committed)
  data/experiments/pass40_reference_benchmark_tarballs.{json,md}
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"
REF = REPO / "data" / "reference_agents"
SDK_CG = REF / "_sdk" / "cg"
TARBALLS = REF / "tarballs"

from ptcg_activegraph.reference_agents import (  # noqa: E402
    EXTERNAL_REFERENCE_STATUS, REFERENCE_AGENTS,
)

CG_MEMBERS = ["__init__.py", "api.py", "game.py", "sim.py", "utils.py", "libcg.so"]
USAGE = "benchmark_opponent_only"
GUARDRAILS = [
    "never uploaded/submitted to Kaggle (no_upload)",
    "never in the submission queue / promoted / family-champion / active-cap",
    "never mutated; not in any mutation lineage; excluded from lifecycle",
    "excluded from 'our best' rankings",
]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _add(tar: tarfile.TarFile, arcname: str, data: bytes) -> None:
    ti = tarfile.TarInfo(arcname)
    ti.size = len(data)
    ti.mtime = 0
    ti.mode = 0o644
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    ti.type = tarfile.REGTYPE
    tar.addfile(ti, io.BytesIO(data))


def _build_deterministic(members: dict[str, bytes]) -> tuple[bytes, str, str]:
    """Return (gz_bytes, content_sha256, tarball_sha256)."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for arc in sorted(members):
            _add(tar, arc, members[arc])
    tar_bytes = raw.getvalue()
    content_sha = _sha256(tar_bytes)
    gz = io.BytesIO()
    with gzip.GzipFile(fileobj=gz, mode="wb", mtime=0) as g:
        g.write(tar_bytes)
    gz_bytes = gz.getvalue()
    return gz_bytes, content_sha, _sha256(gz_bytes)


def main() -> int:
    TARBALLS.mkdir(parents=True, exist_ok=True)
    EXP.mkdir(parents=True, exist_ok=True)

    fetch = json.loads(
        (EXP / "pass40_reference_agent_fetch.json").read_text(encoding="utf-8"))
    cg_sig = {r["agent_id"]: r.get("cg_signature") for r in fetch["agents"]}

    cg_data = {m: (SDK_CG / m).read_bytes() for m in CG_MEMBERS
               if (SDK_CG / m).is_file()}
    sdk_missing = [m for m in CG_MEMBERS if m not in cg_data]

    entries = []
    for spec in REFERENCE_AGENTS:
        mat = REF / "materialized" / spec.agent_id
        main_py = mat / "main.py"
        deck_csv = mat / "deck.csv"
        if not main_py.is_file() or not deck_csv.is_file() or sdk_missing:
            entries.append({"agent_id": spec.agent_id, "built": False,
                            "reason": "missing materialized files or SDK"})
            continue
        members = {"main.py": main_py.read_bytes(),
                   "deck.csv": deck_csv.read_bytes()}
        for m, b in cg_data.items():
            members[f"cg/{m}"] = b
        gz_bytes, content_sha, tarball_sha = _build_deterministic(members)
        out = TARBALLS / f"{spec.agent_id}.tar.gz"
        out.write_bytes(gz_bytes)
        entries.append({
            "agent_id": spec.agent_id, "label": spec.label,
            "kaggle_ref": spec.kaggle_ref, "author": spec.author,
            "deck_archetype": spec.deck_archetype, "source_kind": spec.source_kind,
            "optional": spec.optional, "pool_status": EXTERNAL_REFERENCE_STATUS,
            "usage": USAGE, "built": True,
            "tarball": str(out.relative_to(REPO)),
            "tarball_sha256": tarball_sha, "content_sha256": content_sha,
            "tarball_bytes": len(gz_bytes), "members": sorted(members),
            "main_py_sha256": _sha256(members["main.py"]),
            "deck_csv_sha256": _sha256(members["deck.csv"]),
            "cg_signature": cg_sig.get(spec.agent_id),
            "source_json": f"data/reference_agents/materialized/{spec.agent_id}/source.json",
            "attribution_md": f"data/reference_agents/materialized/{spec.agent_id}/ATTRIBUTION.md",
        })

    built = [e for e in entries if e.get("built")]
    n_built = len(built)
    all_built = n_built == len(REFERENCE_AGENTS) and not sdk_missing

    manifest = {
        "pass": "40", "part": "F", "kind": "reference_agent_manifest",
        "local_only": True, "no_upload": True, "upload_performed": False,
        "auto_submit": False, "github_push": False, "candidate_generation": False,
        "pool_status": EXTERNAL_REFERENCE_STATUS, "usage": USAGE,
        "guardrails": GUARDRAILS, "sdk_members": CG_MEMBERS,
        "sdk_missing": sdk_missing,
        "immutable_note": ("deterministic content_sha256 over the uncompressed tar; "
                           "gzip written with mtime=0 for a stable tarball_sha256; "
                           "tarballs gitignored (bundle libcg.so), hashes committed"),
        "agents_total": len(REFERENCE_AGENTS), "agents_built": n_built,
        "all_built": all_built, "agents": entries,
    }
    (REF / "reference_agent_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "n/a")

    md = [
        "# Reference-agent benchmark manifest (Pass 40, Part F)", "",
        "> Immutable, self-contained **benchmark opponents** "
        f"(`{EXTERNAL_REFERENCE_STATUS}`). Each tarball bundles `cg/` alongside "
        "`main.py` + `deck.csv`. NOT our candidates: never uploaded, promoted, "
        "mutated, queued, or ranked as 'our best'.", "",
        f"- agents built: **{n_built}/{len(REFERENCE_AGENTS)}**  ·  all built: "
        f"**{yn(all_built)}**",
        f"- SDK members bundled: `{', '.join(CG_MEMBERS)}`", "",
        "| agent_id | archetype | optional | tarball_sha256 (gz) | content_sha256 | "
        "bytes |", "|---|---|---|---|---|---|",
    ]
    for e in entries:
        if not e.get("built"):
            md.append(f"| `{e['agent_id']}` | — | — | (not built) | — | — |")
            continue
        md.append(
            f"| `{e['agent_id']}` | {e['deck_archetype']} | {yn(e['optional'])} | "
            f"`{e['tarball_sha256'][:16]}…` | `{e['content_sha256'][:16]}…` | "
            f"{e['tarball_bytes']} |")
    md += ["", "Full hashes + provenance pointers are in "
           "`reference_agent_manifest.json` and each agent's `source.json` / "
           "`ATTRIBUTION.md`."]
    (REF / "reference_agent_manifest.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    # Mirror a copy of the experiment record under data/experiments for the pass.
    (EXP / "pass40_reference_benchmark_tarballs.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    (EXP / "pass40_reference_benchmark_tarballs.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"tarballs: built={n_built}/{len(REFERENCE_AGENTS)} all_built={all_built} "
          f"sdk_missing={sdk_missing}")
    return 0 if all_built else 1


if __name__ == "__main__":
    raise SystemExit(main())
