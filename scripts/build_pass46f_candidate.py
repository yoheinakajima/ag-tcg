#!/usr/bin/env python3
"""PASS 46F (Part E) — build the ONE owned search-calibrated cg_typed candidate.

Assembles ``cg_typed_water_anti_disruption_searchcal_v1.tar.gz`` with a top level
of EXACTLY ``main.py`` + ``deck.csv`` + ``cg/`` (the cg_typed lane contract):

  - main.py  : an ORIGINAL fast turn-planner whose hot path is the VERBATIM
               ``turn_scorer.py`` INLINE_SCORER region (no ``src/`` import, no
               online Search) driven by the embedded Pass-46F calibrated profile.
  - deck.csv : the SELECTED internal source deck, copied BYTE-FOR-BYTE (unchanged).
  - cg/      : the bundled SDK (``cg/{__init__,api,game,sim,utils}.py`` + libcg.so).

The scorer's single source of truth is ``src/ptcg_activegraph/analysis/turn_scorer.py``;
the generator embeds its INLINE region verbatim and the calibrated weights from
``pass46f_score_profile.json``. A parity check re-extracts the embedded region
from the built tarball and asserts it is BYTE-identical AND behaviourally identical
to the repo module on fixtures.

HARD guardrails honoured: NO Kaggle upload/submit, NO GitHub push, NO root
main.py/deck.csv mutation, NO mutation/deletion of any existing tarball, NO public
reference as source/parent. The source deck/tarball is only READ. Output is an
OWNED candidate (public_reference=false, mutation_parent=internal). LOCAL only.
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
sys.path.insert(0, str(ROOT / "src"))

from ptcg_activegraph.analysis import turn_scorer as TS  # noqa: E402
from ptcg_activegraph.replays.fingerprints import deck_fingerprint  # noqa: E402

EXP = ROOT / "data" / "experiments"
PROFILE_JSON = EXP / "pass46f_score_profile.json"
SOURCE_JSON = EXP / "pass46f_source_selection.json"
SDK_CG = ROOT / "data" / "reference_agents" / "_sdk" / "cg"
SUBM = ROOT / "data" / "submissions"
OUT_DIR = SUBM / "candidates_pass46f"
CAND_ID = "cg_typed_water_anti_disruption_searchcal_v1"
OUT_TAR = OUT_DIR / f"{CAND_ID}.tar.gz"
CG_FILES = ["__init__.py", "api.py", "game.py", "sim.py", "utils.py", "libcg.so"]


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _add_bytes(tar: tarfile.TarFile, arc: str, data: bytes, mode: int = 0o644):
    info = tarfile.TarInfo(name=arc)
    info.size = len(data)
    info.mtime = 0  # deterministic
    info.mode = mode
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    tar.addfile(info, io.BytesIO(data))


_MAIN_HEAD = '''\
"""cg_typed candidate entrypoint — {cand_id}.

OWNED PASS-46F search-calibrated FAST TURN-PLANNER candidate. The hot path is the
VERBATIM ``turn_scorer.py`` INLINE_SCORER region (an interpretable linear model
over coarse action families) driven by an embedded profile whose weights were
calibrated OFFLINE against the Pass-46E Search oracle. There is NO online Search
in this path. The deck is the selected internal source deck, copied unchanged.

No reference-agent policy code is copied; the only bundled reference asset is the
``cg`` SDK (allowed). Runtime contract: ``agent(obs_dict) -> list[int]`` of legal
option indices (or the 60 deck card ids on the deck-submission step). Never raises.

LOCAL benchmark-lane feasibility agent — NOT a Kaggle score / leaderboard /
strength claim. NO upload / submit / promote / mutate. Asserts NO exact-damage,
lethal, missed-KO, Boss-gust, spread, or globally-best action.
"""
from __future__ import annotations

import json as _json
import os as _os
import sys as _sys

# --- Bundled cg SDK import (robust to cwd; AST-visible for the cg_typed lane) ---
try:
    from cg import api as _cg
except Exception:  # pragma: no cover - resolve cg/ next to this file, then retry
    try:
        _here = _os.path.dirname(_os.path.abspath(__file__))
        if _here and _here not in _sys.path:
            _sys.path.insert(0, _here)
    except Exception:
        pass
    try:
        from cg import api as _cg
    except Exception:
        _cg = None

# --- Embedded Pass-46F calibrated profile (offline Search-oracle calibrated) ----
# Loaded from a JSON string so the embedded weights are byte-synced with
# data/experiments/pass46f_score_profile.json. Never raises at import.
try:
    _PROFILE = _json.loads(r\'\'\'{profile_json}\'\'\')
except Exception:
    _PROFILE = {{"profile_id": "embedded_fallback", "weights": {{}}}}

# OptionType END marker (mirror cg.api.OptionType; used only by the legal fallback).
OT_END = 14


# ---------------------------------------------------------------------------
# Universal accessors + generic legal-selection contract (never raise).
# ---------------------------------------------------------------------------
def _g(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_int(v, default=None):
    try:
        if isinstance(v, bool):
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


def _get_select(obs):
    s = _g(obs, "select")
    return s if (isinstance(s, dict) or s is not None) else None


def _get_options(select):
    for key in ("option", "options", "choices"):
        v = _g(select, key)
        if isinstance(v, tuple):
            v = list(v)
        if isinstance(v, list):
            return v
    return []


def _min_max(select, n):
    mx = _as_int(_g(select, "maxCount"), 1 if n else 0)
    mn = _as_int(_g(select, "minCount"), 0)
    mx = 0 if mx is None or mx < 0 else min(mx, n)
    mn = 0 if mn is None or mn < 0 else mn
    if mn > mx:
        mn = mx
    return mn, mx


def _fallback_action(n, mn, mx):
    if n <= 0 or mx <= 0:
        return []
    mx = min(mx, n)
    mn = max(0, min(mn, mx))
    if mx == 1:
        return [0]
    take = mn if mn > 0 else mx
    return list(range(min(take, n)))


def _validate(result, n, mn, mx):
    if n <= 0 or mx <= 0:
        return []
    if not isinstance(result, (list, tuple)):
        result = []
    seen, out = set(), []
    for it in result:
        idx = _as_int(it)
        if idx is not None and 0 <= idx < n and idx not in seen:
            seen.add(idx)
            out.append(idx)
    if len(out) > mx:
        out = out[:mx]
    if len(out) < mn:
        for idx in range(n):
            if len(out) >= mn:
                break
            if idx not in seen:
                seen.add(idx)
                out.append(idx)
    if not out and (mn > 0 or mx >= 1):
        return _fallback_action(n, mn, mx)
    return out


# ---------------------------------------------------------------------------
# Deck-return plumbing (own deck; resilient to cwd; harness may inject _DECK_IDS).
# ---------------------------------------------------------------------------
_DECK_IDS = None
_EMBEDDED_DECK = {embedded_deck}


def _deck_paths():
    paths = []
    try:
        here = _os.path.dirname(_os.path.abspath(__file__))
        paths.append(_os.path.join(here, "deck.csv"))
    except Exception:
        pass
    paths.append("deck.csv")
    paths.append("/kaggle_simulations/agent/deck.csv")
    return paths


def _load_deck_ids():
    global _DECK_IDS
    if _DECK_IDS:
        return _DECK_IDS
    ids = []
    for p in _deck_paths():
        try:
            if not _os.path.exists(p):
                continue
            parsed = []
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        v = _as_int(line)
                        if v is not None:
                            parsed.append(v)
            if len(parsed) == 60:
                ids = parsed
                break
            if parsed and not ids:
                ids = parsed
        except Exception:
            continue
    if len(ids) != 60:
        ids = list(_EMBEDDED_DECK)
    _DECK_IDS = ids
    return _DECK_IDS


'''


_MAIN_TAIL = '''

# ---------------------------------------------------------------------------
# Entrypoint — fast calibrated turn-planner over raw options (no online Search).
# ---------------------------------------------------------------------------
def agent(obs_dict):
    """Kaggle/cg entrypoint. Always returns list[int] of legal indices."""
    # 0. Deck-submission step (select present but null) -> return 60 card ids.
    try:
        if isinstance(obs_dict, dict) and "select" in obs_dict \\
                and obs_dict["select"] is None:
            deck = _load_deck_ids()
            if len(deck) == 60:
                return deck
    except Exception:
        pass

    select = _get_select(obs_dict)
    options = _get_options(select)
    n = len(options)
    mn, mx = _min_max(select, n)
    if n == 0 or mx <= 0:
        return []

    # 1. Fast calibrated scorer over the raw options (inlined, never-raise).
    try:
        board = obs_dict.get("current") if isinstance(obs_dict, dict) else None
        decision = choose_indices(select, board, _PROFILE)
    except Exception:
        decision = None
    if decision:
        out = _validate(decision, n, mn, mx)
        if out:
            return out

    # 2. Generic legal fallback: prefer an action over ending the turn.
    try:
        if mx == 1:
            for i, o in enumerate(options):
                if _as_int(_g(o, "type")) != OT_END:
                    return [i]
            return [0]
    except Exception:
        pass
    return _validate(_fallback_action(n, mn, mx), n, mn, mx)


if __name__ == "__main__":
    demo = {"logs": [], "current": None,
            "select": {"option": [{"type": 13}, {"type": 8}, {"type": 14}],
                       "maxCount": 1, "minCount": 0}}
    print("demo:", agent(demo))
'''


def build_main_py(region: str, profile_obj: dict, deck_ids: list[int]) -> str:
    profile_json = json.dumps(profile_obj, indent=2, sort_keys=True)
    if "'''" in profile_json:
        raise SystemExit("profile JSON contains triple-quote; cannot embed safely")
    head = _MAIN_HEAD.format(
        cand_id=CAND_ID, profile_json=profile_json,
        embedded_deck=repr(list(deck_ids)))
    return head + region.rstrip("\n") + "\n" + _MAIN_TAIL


def _extract_region(text: str) -> str:
    begin = "# ===================== INLINE_SCORER_BEGIN ====================="
    end = "# ===================== INLINE_SCORER_END ====================="
    i = text.index(begin)
    j = text.index(end) + len(end)
    return text[i:j] + "\n"


def _behavioral_parity(extracted_region: str, profile: dict) -> dict:
    """Exec the extracted region standalone; compare choose_indices to the repo."""
    ns: dict = {}
    exec(extracted_region, ns)  # noqa: S102 - trusted, self-built region
    fixtures = [
        {"option": [{"type": 13}, {"type": 8}, {"type": 14}],
         "minCount": 1, "maxCount": 1},
        {"option": [{"type": 9}, {"type": 7}, {"type": 14}],
         "minCount": 1, "maxCount": 1},
        {"option": [{"type": 8}, {"type": 8}, {"type": 3}],
         "minCount": 2, "maxCount": 2},
        {"option": [{"type": 0}], "minCount": 0, "maxCount": 0},
        {"option": [{"type": 99}, {"type": 14}], "minCount": 1, "maxCount": 1},
        "garbage-not-a-dict",
    ]
    mism = []
    for fx in fixtures:
        a = TS.choose_indices(fx, None, profile)
        b = ns["choose_indices"](fx, None, profile)
        if a != b:
            mism.append({"fixture": fx, "repo": a, "inlined": b})
    # also a score_option parity sample
    sp_mismatch = []
    for fam_opt in ({"type": 8}, {"type": 13}, {"type": 14}, {"type": 99}):
        fa = TS.score_option(TS.extract_features(fam_opt), profile)
        fb = ns["score_option"](ns["extract_features"](fam_opt), profile)
        if fa != fb:
            sp_mismatch.append({"option": fam_opt, "repo": fa, "inlined": fb})
    return {"choose_indices_mismatches": mism,
            "score_option_mismatches": sp_mismatch,
            "behavioral_parity_ok": not mism and not sp_mismatch}


def build() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for req in (PROFILE_JSON, SOURCE_JSON, SDK_CG):
        if not req.exists():
            raise SystemExit(f"missing required input: {req}")

    profile_data = json.loads(PROFILE_JSON.read_text(encoding="utf-8"))
    profile = profile_data["calibrated_profile"]
    source = json.loads(SOURCE_JSON.read_text(encoding="utf-8"))
    sel = source.get("selected_source") or {}
    parent_id = source.get("parent_candidate_id")
    src_tarball = SUBM / sel["tarball_path"]
    if not src_tarball.exists():
        raise SystemExit(f"source tarball missing: {src_tarball}")

    # READ source deck byte-for-byte from its tarball (never mutate the tarball).
    with tarfile.open(src_tarball, "r:gz") as st:
        deck_bytes = st.extractfile("deck.csv").read()
    deck_ids = [int(x) for x in deck_bytes.decode("utf-8").split() if x.strip()]
    if len(deck_ids) != 60:
        raise SystemExit(f"source deck has {len(deck_ids)} rows, expected 60")

    region = TS.inline_region_source()
    if not region or "INLINE_SCORER_BEGIN" not in region:
        raise SystemExit("could not extract INLINE_SCORER region from turn_scorer")

    main_src = build_main_py(region, profile, deck_ids)
    main_bytes = main_src.encode("utf-8")

    cg_members = []
    for fn in CG_FILES:
        fp = SDK_CG / fn
        if not fp.is_file():
            raise SystemExit(f"missing cg SDK file: {fp}")
        cg_members.append((f"cg/{fn}", fp.read_bytes()))

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=9) as tar:
        _add_bytes(tar, "main.py", main_bytes)
        _add_bytes(tar, "deck.csv", deck_bytes)
        for arc, data in cg_members:
            _add_bytes(tar, arc, data, mode=(0o755 if arc.endswith(".so") else 0o644))
    tar_bytes = buf.getvalue()
    OUT_TAR.write_bytes(tar_bytes)

    with tarfile.open(OUT_TAR, "r:gz") as tar:
        names = [m.name for m in tar.getmembers() if m.isfile()]
        extracted_main = tar.extractfile("main.py").read().decode("utf-8")
    top = sorted({n.split("/", 1)[0] for n in names})
    assert top == ["cg", "deck.csv", "main.py"], f"unexpected top-level: {top}"
    assert not any("__pycache__" in n for n in names), "pycache leaked"

    # ---- Parity: embedded region byte-identical + behaviourally identical ----
    embedded_region = _extract_region(extracted_main)
    region_byte_identical = (embedded_region == region)
    parity = _behavioral_parity(embedded_region, profile)

    rec = {
        "pass": "46f", "part": "E", "candidate_id": CAND_ID,
        "tarball": str(OUT_TAR.relative_to(ROOT)), "tarball_sha256": _sha(tar_bytes),
        "tarball_bytes": len(tar_bytes), "lane": "cg_typed",
        "owned_candidate": True, "public_reference": False,
        "mutation_parent": "internal", "parent_candidate_id": parent_id,
        "parent_family": sel.get("family_id"),
        "parent_source_tarball": str(src_tarball.relative_to(ROOT)),
        "deck_unchanged": True, "deck_sha256": _sha(deck_bytes),
        "deck_rows": len(deck_ids),
        "deck_fingerprint": deck_fingerprint(deck_ids),
        "source_deck_fingerprint": sel.get("deck_fingerprint"),
        "main_py_sha256": _sha(main_bytes), "main_py_bytes": len(main_bytes),
        "scorer_source_module": "src/ptcg_activegraph/analysis/turn_scorer.py",
        "scorer_schema_version": TS.PROFILE_SCHEMA_VERSION,
        "profile_id": profile.get("profile_id"),
        "profile_calibrated": profile.get("calibrated"),
        "no_online_search": True,
        "inline_region_byte_identical": region_byte_identical,
        "inline_region_sha256": _sha(region.encode("utf-8")),
        "parity": parity,
        "cg_sdk_source": str(SDK_CG.relative_to(ROOT)), "cg_files": CG_FILES,
        "members": sorted(names), "top_level": top, "no_upload": True,
        "local_only": True, "production_mutated": False,
        "guardrails": {
            "no_kaggle_upload": True, "no_github_push": True,
            "root_main_deck_untouched": True,
            "no_tarball_mutation_or_deletion": True,
            "no_reference_agent_code_copied": True,
            "no_public_reference_as_source_or_parent": True,
            "no_online_search_in_hot_path": True,
        },
        "built_at_epoch": int(time.time()),
    }
    return rec


def run_validator() -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate_cg_typed_tarball.py"),
         str(OUT_TAR), "--import-smoke"],
        capture_output=True, text=True)
    return {"returncode": proc.returncode, "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip()}


def main() -> int:
    rec = build()
    rec["cg_typed_validator"] = run_validator()
    rec["cg_typed_static_pass"] = (rec["cg_typed_validator"]["returncode"] == 0)

    (EXP / "pass46f_candidate_build.json").write_text(
        json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46F (Part E) — Owned search-calibrated cg_typed candidate", "",
        "_LOCAL benchmark-lane feasibility candidate. NOT a Kaggle score / "
        "leaderboard / strength claim. No upload, submit, push, root mutation, "
        "or tarball mutation. No public reference as source/parent. No online "
        "Search in the hot path. No exact-damage / lethal / best-action claim._", "",
        f"- **candidate id:** `{rec['candidate_id']}`",
        f"- **tarball:** `{rec['tarball']}` ({rec['tarball_bytes']} bytes)",
        f"- **tarball sha256:** `{rec['tarball_sha256']}`",
        f"- **lane:** {rec['lane']} (owned, public_reference=false, "
        f"mutation_parent=internal)",
        f"- **parent (internal source):** `{rec['parent_candidate_id']}` "
        f"({rec['parent_family']})",
        f"- **deck:** byte-copied unchanged from source "
        f"(sha256 `{rec['deck_sha256']}`, {rec['deck_rows']} rows)",
        f"- **profile:** `{rec['profile_id']}` (calibrated={rec['profile_calibrated']}, "
        f"schema {rec['scorer_schema_version']})",
        f"- **inline region byte-identical to repo scorer:** "
        f"{rec['inline_region_byte_identical']}",
        f"- **behavioural parity (repo vs inlined):** "
        f"{rec['parity']['behavioral_parity_ok']}",
        f"- **cg_typed static validator:** "
        f"{'PASS' if rec['cg_typed_static_pass'] else 'FAIL'} — "
        f"`{rec['cg_typed_validator']['stdout']}`",
        "", "## Originality",
        "main.py is an original fast turn-planner: the interpretable INLINE_SCORER "
        "region (linear model over coarse action families) embedded VERBATIM from "
        "`turn_scorer.py`, driven by the offline Search-oracle-calibrated profile. "
        "No reference-agent policy code is copied; only the allowed `cg/` SDK is "
        "bundled. No online Search runs in the live hot path.", "",
        "## Guardrails",
    ]
    for k, v in rec["guardrails"].items():
        md.append(f"- {k}: {v}")
    (EXP / "pass46f_candidate_build.md").write_text("\n".join(md) + "\n",
                                                    encoding="utf-8")

    print(json.dumps({
        "built": rec["tarball"], "sha256": rec["tarball_sha256"],
        "inline_byte_identical": rec["inline_region_byte_identical"],
        "behavioral_parity_ok": rec["parity"]["behavioral_parity_ok"],
        "cg_typed_static_pass": rec["cg_typed_static_pass"],
        "validator": rec["cg_typed_validator"]["stdout"]}, indent=2))
    ok = (rec["cg_typed_static_pass"] and rec["inline_region_byte_identical"]
          and rec["parity"]["behavioral_parity_ok"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
