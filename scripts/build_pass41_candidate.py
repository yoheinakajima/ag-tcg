#!/usr/bin/env python3
"""Build the ONE owned cg_typed PASS-41 candidate tarball (Part E).

Assembles ``cg_typed_mono_lightning_miraidon_policy_v1.tar.gz`` with a top level
of EXACTLY ``main.py`` + ``deck.csv`` + ``cg/`` (the cg_typed lane contract):

  - main.py  : the ORIGINAL typed policy (data/experiments/pass41_cg_typed_main_src.py)
  - deck.csv : the selected parent's deck, copied BYTE-FOR-BYTE (unchanged)
  - cg/      : the SDK from data/reference_agents/_sdk/cg (no reference *agent* code)

HARD guardrails honoured here: NO Kaggle upload/submit, NO GitHub push, NO root
main.py/deck.csv mutation, NO mutation/deletion of any existing tarball. The
parent deck is only READ. The output is an OWNED candidate
(public_reference=false, mutation_parent=internal).

Writes the tarball + data/experiments/pass41_candidate_build.{json,md} and runs
the cg_typed static validator on the result.
"""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_MAIN = ROOT / "data/experiments/pass41_cg_typed_main_src.py"
PARENT_DIR = ROOT / "data/tournament/benchmark/_our_extracted/mono_lightning_miraidon_easy"
PARENT_DECK = PARENT_DIR / "deck.csv"
SDK_CG = ROOT / "data/reference_agents/_sdk/cg"
OUT_DIR = ROOT / "data/submissions/candidates_pass41"
CAND_ID = "cg_typed_mono_lightning_miraidon_policy_v1"
OUT_TAR = OUT_DIR / f"{CAND_ID}.tar.gz"
CG_FILES = ["__init__.py", "api.py", "game.py", "sim.py", "utils.py", "libcg.so"]


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file(p: Path) -> str:
    return _sha256_bytes(p.read_bytes())


def _add_bytes(tar: tarfile.TarFile, arcname: str, data: bytes, mode: int = 0o644):
    info = tarfile.TarInfo(name=arcname)
    info.size = len(data)
    info.mtime = 0  # deterministic
    info.mode = mode
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    tar.addfile(info, io.BytesIO(data))


def build() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for req in (SRC_MAIN, PARENT_DECK, SDK_CG):
        if not req.exists():
            raise SystemExit(f"missing required input: {req}")

    main_bytes = SRC_MAIN.read_bytes()
    deck_bytes = PARENT_DECK.read_bytes()  # copied unchanged
    deck_rows = [int(x) for x in deck_bytes.decode("utf-8").split() if x.strip()]
    if len(deck_rows) != 60:
        raise SystemExit(f"parent deck.csv has {len(deck_rows)} rows, expected 60")

    cg_members: list[tuple[str, bytes]] = []
    for fn in CG_FILES:
        fp = SDK_CG / fn
        if not fp.is_file():
            raise SystemExit(f"missing cg SDK file: {fp}")
        cg_members.append((f"cg/{fn}", fp.read_bytes()))

    # Build deterministic tarball; NEVER include __pycache__ or extra top-level.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=9) as tar:
        _add_bytes(tar, "main.py", main_bytes)
        _add_bytes(tar, "deck.csv", deck_bytes)
        for arc, data in cg_members:
            _add_bytes(tar, arc, data, mode=(0o755 if arc.endswith(".so") else 0o644))
    tar_bytes = buf.getvalue()
    OUT_TAR.write_bytes(tar_bytes)

    # Re-open to assert exact top-level membership.
    with tarfile.open(OUT_TAR, "r:gz") as tar:
        names = [m.name for m in tar.getmembers() if m.isfile()]
    top = sorted({n.split("/", 1)[0] for n in names})
    assert top == ["cg", "deck.csv", "main.py"], f"unexpected top-level: {top}"
    assert not any("__pycache__" in n for n in names), "pycache leaked into tarball"

    record = {
        "pass": 41,
        "part": "E",
        "candidate_id": CAND_ID,
        "tarball": str(OUT_TAR.relative_to(ROOT)),
        "tarball_sha256": _sha256_bytes(tar_bytes),
        "tarball_bytes": len(tar_bytes),
        "lane": "cg_typed",
        "owned_candidate": True,
        "public_reference": False,
        "mutation_parent": "internal",
        "parent_family": "mono_lightning_miraidon_easy",
        "parent_deck_source": str(PARENT_DECK.relative_to(ROOT)),
        "deck_unchanged": True,
        "deck_sha256": _sha256_bytes(deck_bytes),
        "deck_rows": len(deck_rows),
        "main_py_source": str(SRC_MAIN.relative_to(ROOT)),
        "main_py_sha256": _sha256_bytes(main_bytes),
        "cg_sdk_source": str(SDK_CG.relative_to(ROOT)),
        "cg_files": CG_FILES,
        "members": sorted(names),
        "top_level": top,
        "no_upload": True,
        "guardrails": {
            "no_kaggle_upload": True, "no_github_push": True,
            "root_main_deck_untouched": True, "no_tarball_mutation_or_deletion": True,
            "no_reference_agent_code_copied": True, "cg_sdk_bundled_allowed": True,
        },
        "built_at_epoch": int(time.time()),
    }
    return record


def run_validator() -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate_cg_typed_tarball.py"),
         str(OUT_TAR)],
        capture_output=True, text=True)
    return {"returncode": proc.returncode,
            "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()}


def main() -> int:
    rec = build()
    rec["cg_typed_validator"] = run_validator()
    rec["cg_typed_static_pass"] = (rec["cg_typed_validator"]["returncode"] == 0)

    out_json = ROOT / "data/experiments/pass41_candidate_build.json"
    out_json.write_text(json.dumps(rec, indent=2), encoding="utf-8")

    md = [
        "# Pass 41 (Part E) — Owned cg_typed Candidate Build",
        "",
        "_LOCAL benchmark-lane feasibility candidate. NOT a Kaggle score / leaderboard /",
        "strength claim. No upload, submit, push, root mutation, or tarball mutation._",
        "",
        f"- **candidate id:** `{rec['candidate_id']}`",
        f"- **tarball:** `{rec['tarball']}` ({rec['tarball_bytes']} bytes)",
        f"- **tarball sha256:** `{rec['tarball_sha256']}`",
        f"- **lane:** {rec['lane']} (owned_candidate, public_reference=false, "
        f"mutation_parent=internal)",
        f"- **parent family:** {rec['parent_family']} "
        f"(deck copied byte-for-byte, unchanged; sha256 `{rec['deck_sha256']}`, "
        f"{rec['deck_rows']} rows)",
        f"- **main.py source:** `{rec['main_py_source']}` "
        f"(sha256 `{rec['main_py_sha256']}`)",
        f"- **cg/ bundled from:** `{rec['cg_sdk_source']}` "
        f"({', '.join(rec['cg_files'])})",
        f"- **top-level entries:** {rec['top_level']} (exactly main.py + deck.csv + cg/)",
        f"- **cg_typed static validator:** "
        f"{'PASS' if rec['cg_typed_static_pass'] else 'FAIL'} — "
        f"`{rec['cg_typed_validator']['stdout']}`",
        "",
        "## Originality",
        "main.py is an original typed Miraidon policy (cg enums + card/attack DB +",
        "prize/HP/energy/deck reasoning). No reference-agent policy code was copied; the",
        "only bundled reference asset is the `cg/` SDK, which the spec explicitly allows.",
        "",
        "## Guardrails",
    ]
    for k, v in rec["guardrails"].items():
        md.append(f"- {k}: {v}")
    (ROOT / "data/experiments/pass41_candidate_build.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"built": rec["tarball"],
                      "sha256": rec["tarball_sha256"],
                      "cg_typed_static_pass": rec["cg_typed_static_pass"],
                      "validator": rec["cg_typed_validator"]["stdout"]}, indent=2))
    return 0 if rec["cg_typed_static_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
