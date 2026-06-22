#!/usr/bin/env python3
"""PASS 46H (Part F) — build the SMALL BATCH of owned cg_typed per-option-value candidates.

For every (source family x profile) pair selected in Part B this assembles one
``cg_typed`` tarball whose top level is EXACTLY ``main.py`` + ``deck.csv`` + ``cg/``:

  - main.py  : an ORIGINAL fast within-family per-OPTION value planner whose hot path is
               the VERBATIM ``option_value_features.py`` INLINE_OPTION_VALUE_V0 region
               (no ``src/`` import, NO online Search), driven by the embedded Pass-46H
               profile (family floor weights + interpretable per-option role/target
               priors + this deck's OWN role map as JSON profile data).
  - deck.csv : the SELECTED internal source deck, copied BYTE-FOR-BYTE (unchanged).
  - cg/      : the bundled SDK (allowed reference asset).

The scorer's single source of truth is
``src/ptcg_activegraph/analysis/option_value_features.py``; the generator embeds its
INLINE region verbatim and the deck's profiles from ``pass46h_role_maps.json``. A parity
check re-extracts the embedded region from each built tarball and asserts it is
BYTE-identical AND behaviourally identical to the repo module on fixtures.

HARD guardrails honoured: NO Kaggle upload/submit, NO GitHub push, NO root
main.py/deck.csv mutation, NO mutation/overwrite-with-different-bytes of any EXISTING
(other-pass) tarball (output goes to a NEW ``candidates_pass46h/`` dir), NO public
reference as source/parent. Source decks/tarballs are only READ. Outputs are OWNED
candidates (public_reference=false, mutation_parent=internal). LOCAL only; no events,
no promotion, no queue, no registration.
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

from ptcg_activegraph.analysis import option_value_features as OV  # noqa: E402
from ptcg_activegraph.replays.fingerprints import deck_fingerprint  # noqa: E402

EXP = ROOT / "data" / "experiments"
SOURCE_JSON = EXP / "pass46h_source_selection.json"
ROLE_MAPS_JSON = EXP / "pass46h_role_maps.json"
SDK_CG = ROOT / "data" / "reference_agents" / "_sdk" / "cg"
SUBM = ROOT / "data" / "submissions"
OUT_DIR = SUBM / "candidates_pass46h"
CG_FILES = ["__init__.py", "api.py", "game.py", "sim.py", "utils.py", "libcg.so"]
MAX_BATCH = 6
BUILD_PROFILE_IDS = ("family_only_floor_v1", "option_value_v1",
                     "conservative_option_value_v1")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _add_bytes(tar: tarfile.TarFile, arc: str, data: bytes, mode: int = 0o644):
    info = tarfile.TarInfo(name=arc)
    info.size = len(data)
    info.mtime = 0
    info.mode = mode
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    tar.addfile(info, io.BytesIO(data))


_MAIN_HEAD = '''\
"""cg_typed candidate entrypoint — {cand_id}.

OWNED PASS-46H within-family per-OPTION value FAST planner. The hot path is the VERBATIM
``option_value_features.py`` INLINE_OPTION_VALUE_V0 region (an interpretable linear model
over coarse action families PLUS option-specific VISIBLE features: the resolved card's
coarse role bucket, the in-play target's area/energy-count + role, and an
end-with-productive-alternatives penalty) driven by the embedded Pass-46H profile. There
is NO online Search in this path. The deck is the selected internal source deck, unchanged.

Card identity is resolved from the option's own area/index against YOUR visible hand or
the OFFERED select list; the target is read from the option's inPlayArea/inPlayIndex over
YOUR own board. NO hidden hand / deck / prize contents are read. Role buckets are coarse
deck-composition labels; NEITHER they nor the target area are a lethal / KO / exact-damage
/ Boss-gust / spread / globally-best-action / card-value claim.

No reference-agent policy code is copied; the only bundled reference asset is the ``cg``
SDK (allowed). Runtime contract: ``agent(obs_dict) -> list[int]`` of legal option indices
(or the 60 deck card ids on the deck-submission step). Never raises.

LOCAL benchmark-lane feasibility agent — NOT a Kaggle score / leaderboard / strength
claim. NO upload / submit / promote / mutate.
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

# --- Embedded Pass-46H per-option value profile (family floor + option priors + role map)
# Loaded from a JSON string so the embedded profile is byte-synced with this deck's entry
# in data/experiments/pass46h_role_maps.json. Never raises at import.
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
# Entrypoint — fast per-option value planner over raw options (no online Search).
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

    # 1. Fast per-option value scorer over the raw options (inlined, never-raise).
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


def build_main_py(region: str, profile_obj: dict, deck_ids, cand_id: str) -> str:
    profile_json = json.dumps(profile_obj, indent=2, sort_keys=True)
    if "'''" in profile_json:
        raise SystemExit("profile JSON contains triple-quote; cannot embed safely")
    head = _MAIN_HEAD.format(
        cand_id=cand_id, profile_json=profile_json,
        embedded_deck=repr(list(deck_ids)))
    return head + region.rstrip("\n") + "\n" + _MAIN_TAIL


def _extract_region(text: str) -> str:
    begin = "# ================== INLINE_OPTION_VALUE_V0_BEGIN =================="
    end = "# ================== INLINE_OPTION_VALUE_V0_END =================="
    i = text.index(begin)
    j = text.index(end) + len(end)
    return text[i:j] + "\n"


# Parity fixtures: exercise resolve (hand/deck), target (active/bench), end-with-alts.
_PARITY_BOARDS = [
    None,
    {"yourIndex": 0, "players": [
        {"hand": [{"id": 3}, {"id": 100}, {"id": 200}],
         "active": [{"id": 700, "energies": []}],
         "bench": [{"id": 701, "energyCards": [{"id": 3}]}]},
        {"active": [{"id": 900}], "bench": []}]},
    {"yourIndex": 1, "players": [
        {"active": [{"id": 1}], "bench": []},
        {"hand": [{"id": 3}], "active": [{"id": 800, "energies": [{"id": 3}]}],
         "bench": [{"id": 801, "energies": []}]}]},
]
_PARITY_SELECTS = [
    {"option": [{"type": 13, "attackId": 1}, {"type": 8, "area": 2, "index": 0},
                {"type": 14}], "minCount": 1, "maxCount": 1},
    {"option": [{"type": 8, "area": 2, "index": 0, "inPlayArea": 4, "inPlayIndex": 0},
                {"type": 8, "area": 2, "index": 0, "inPlayArea": 5, "inPlayIndex": 0}],
     "minCount": 1, "maxCount": 1},
    {"option": [{"type": 3, "area": 1, "index": 0}, {"type": 3, "area": 1, "index": 1},
                {"type": 3, "area": 1, "index": 2}], "minCount": 1, "maxCount": 1,
     "deck": [{"id": 100}, {"id": 200}, {"id": 300}]},
    {"option": [{"type": 7, "index": 0}, {"type": 7, "index": 1}, {"type": 14}],
     "minCount": 1, "maxCount": 1},
    {"option": [{"type": 8}, {"type": 8}, {"type": 3}], "minCount": 2, "maxCount": 2},
    {"option": [{"type": 0}], "minCount": 0, "maxCount": 0},
    {"option": [{"type": 99}, {"type": 14}], "minCount": 1, "maxCount": 1},
]


def _behavioral_parity(extracted_region: str, profile: dict) -> dict:
    ns: dict = {}
    exec(extracted_region, ns)  # noqa: S102 - trusted, self-built region
    ci_mism, so_mism, fam_mism = [], [], []
    for sel in _PARITY_SELECTS + ["garbage-not-a-dict"]:
        for board in _PARITY_BOARDS:
            a = OV.choose_indices(sel, board, profile)
            b = ns["choose_indices"](sel, board, profile)
            if a != b:
                ci_mism.append({"select": sel, "board": board, "repo": a, "inlined": b})
            ra = OV.score_options(sel, board, profile)
            rb = ns["score_options"](sel, board, profile)
            if ra != rb:
                so_mism.append({"select": sel, "board": board})
    for sel in _PARITY_SELECTS:
        opts = sel.get("option") if isinstance(sel, dict) else None
        if not isinstance(opts, list):
            continue
        for board in _PARITY_BOARDS:
            for opt in opts:
                fa = OV.score_option(OV.extract_features(opt, sel, board), profile)
                fb = ns["score_option"](ns["extract_features"](opt, sel, board), profile)
                if fa != fb:
                    fam_mism.append({"option": opt, "repo": fa, "inlined": fb})
    return {"choose_indices_mismatches": ci_mism,
            "score_options_mismatches": so_mism,
            "score_option_mismatches": fam_mism,
            "behavioral_parity_ok": not ci_mism and not so_mism and not fam_mism}


def _read_source_deck(tarball: Path):
    with tarfile.open(tarball, "r:gz") as st:
        deck_bytes = st.extractfile("deck.csv").read()
    deck_ids = [int(x) for x in deck_bytes.decode("utf-8").split() if x.strip()]
    return deck_bytes, deck_ids


def build_one(entry: dict, profile_id: str, profile: dict, region: str,
              cg_members) -> dict:
    family = entry["family_id"]
    parent_id = entry["candidate_id"]
    cand_id = f"cg_typed_{family}_{profile_id}"
    out_tar = OUT_DIR / f"{cand_id}.tar.gz"
    if OUT_DIR.resolve() not in out_tar.resolve().parents:
        raise SystemExit(f"refusing to write outside {OUT_DIR}: {out_tar}")

    src_tarball = SUBM / entry["tarball_path"]
    if not src_tarball.exists():
        raise SystemExit(f"source tarball missing: {src_tarball}")
    deck_bytes, deck_ids = _read_source_deck(src_tarball)
    if len(deck_ids) != 60:
        raise SystemExit(f"{parent_id} deck has {len(deck_ids)} rows, expected 60")

    # Lexicographic safety: option value must stay strictly below LEX_SCALE so the
    # conservative profile's family layer always dominates.
    rm = profile.get("role_map") or {}
    ow = profile.get("option_weights")
    max_ov = OV.max_abs_option_value(rm, ow) if ow else 0.0
    if max_ov >= OV.LEX_SCALE:
        raise SystemExit(f"{cand_id}: max|option_value| {max_ov} >= LEX_SCALE")

    main_src = build_main_py(region, profile, deck_ids, cand_id)
    main_bytes = main_src.encode("utf-8")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=9) as tar:
        _add_bytes(tar, "main.py", main_bytes)
        _add_bytes(tar, "deck.csv", deck_bytes)
        for arc, data in cg_members:
            _add_bytes(tar, arc, data, mode=(0o755 if arc.endswith(".so") else 0o644))
    tar_bytes = buf.getvalue()
    # Fail-closed: never overwrite an EXISTING tarball with DIFFERENT bytes (the outer
    # gzip wrapper is not reproducible, so identical content still differs byte-wise).
    if out_tar.exists():
        if out_tar.read_bytes() != tar_bytes:
            raise SystemExit(
                f"refusing to overwrite existing tarball with different bytes: {out_tar}")
    else:
        out_tar.write_bytes(tar_bytes)

    with tarfile.open(out_tar, "r:gz") as tar:
        names = [m.name for m in tar.getmembers() if m.isfile()]
        extracted_main = tar.extractfile("main.py").read().decode("utf-8")
    top = sorted({n.split("/", 1)[0] for n in names})
    assert top == ["cg", "deck.csv", "main.py"], f"unexpected top-level: {top}"
    assert not any("__pycache__" in n for n in names), "pycache leaked"

    embedded_region = _extract_region(extracted_main)
    region_byte_identical = (embedded_region == region)
    parity = _behavioral_parity(embedded_region, profile)

    return {
        "candidate_id": cand_id,
        "tarball": str(out_tar.relative_to(ROOT)), "tarball_sha256": _sha(tar_bytes),
        "tarball_bytes": len(tar_bytes), "lane": "cg_typed",
        "owned_candidate": True, "public_reference": False,
        "mutation_parent": "internal", "parent_candidate_id": parent_id,
        "parent_family": family, "parent_archetype": entry.get("archetype"),
        "parent_source_tarball": str(src_tarball.relative_to(ROOT)),
        "deck_unchanged": True, "deck_sha256": _sha(deck_bytes),
        "deck_rows": len(deck_ids), "deck_fingerprint": deck_fingerprint(deck_ids),
        "source_deck_fingerprint": entry.get("deck_fingerprint"),
        "deck_fingerprint_matches_source":
            deck_fingerprint(deck_ids) == entry.get("deck_fingerprint"),
        "main_py_sha256": _sha(main_bytes), "main_py_bytes": len(main_bytes),
        "scorer_source_module":
            "src/ptcg_activegraph/analysis/option_value_features.py",
        "scorer_schema_version": OV.PROFILE_SCHEMA_VERSION,
        "profile_id": profile.get("profile_id"),
        "scoring_mode": profile.get("scoring_mode"),
        "profile_calibrated": profile.get("calibrated"),
        "role_map_entries": len(rm),
        "max_abs_option_value": round(max_ov, 4),
        "lex_scale": OV.LEX_SCALE,
        "no_online_search": True,
        "inline_region_byte_identical": region_byte_identical,
        "inline_region_sha256": _sha(region.encode("utf-8")),
        "parity": parity,
        "members": sorted(names), "top_level": top,
    }


def run_validator(tarball: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate_cg_typed_tarball.py"),
         str(tarball), "--import-smoke"],
        capture_output=True, text=True)
    return {"returncode": proc.returncode, "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip()}


def build() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for req in (SOURCE_JSON, ROLE_MAPS_JSON, SDK_CG):
        if not req.exists():
            raise SystemExit(f"missing required input: {req}")

    source = json.loads(SOURCE_JSON.read_text(encoding="utf-8"))
    role_maps = json.loads(ROLE_MAPS_JSON.read_text(encoding="utf-8"))
    build_set = [s for s in source["sources"] if s.get("eligible")]

    for entry in build_set:
        if entry.get("checks", {}).get("internal_not_public_ref") is False:
            raise SystemExit(f"public reference as source/parent forbidden: {entry}")

    region = OV.inline_region_source()
    if not region or "INLINE_OPTION_VALUE_V0_BEGIN" not in region:
        raise SystemExit("could not extract INLINE_OPTION_VALUE_V0 region")

    cg_members = []
    for fn in CG_FILES:
        fp = SDK_CG / fn
        if not fp.is_file():
            raise SystemExit(f"missing cg SDK file: {fp}")
        cg_members.append((f"cg/{fn}", fp.read_bytes()))

    pairs = [(entry, pid) for entry in build_set for pid in BUILD_PROFILE_IDS]
    if len(pairs) > MAX_BATCH:
        raise SystemExit(f"batch {len(pairs)} exceeds MAX_BATCH {MAX_BATCH}")

    candidates = []
    skipped = []
    for entry, pid in pairs:
        fam = entry["family_id"]
        rm = (role_maps.get(fam) or {}).get("role_map") or {}
        if not rm:
            skipped.append({"family": fam, "profile": pid, "reason": "empty_role_map"})
            continue
        profile = OV.default_profiles(rm)[pid]
        rec = build_one(entry, pid, profile, region, cg_members)
        rec["cg_typed_validator"] = run_validator(
            OUT_DIR / f"{rec['candidate_id']}.tar.gz")
        rec["cg_typed_static_pass"] = (rec["cg_typed_validator"]["returncode"] == 0)
        rec["candidate_ok"] = bool(
            rec["cg_typed_static_pass"] and rec["inline_region_byte_identical"]
            and rec["parity"]["behavioral_parity_ok"]
            and rec["deck_unchanged"] and rec["deck_rows"] == 60)
        candidates.append(rec)

    return {
        "pass": "46H", "part": "F", "read_only": False, "local_only": True,
        "no_upload": True, "production_mutated": False, "candidate_generated": True,
        "lane": "cg_typed", "n_candidates": len(candidates), "max_batch": MAX_BATCH,
        "skipped": skipped,
        "source_families": sorted({e["family_id"] for e in build_set}),
        "build_profile_ids": list(BUILD_PROFILE_IDS),
        "scorer_source_module":
            "src/ptcg_activegraph/analysis/option_value_features.py",
        "scorer_schema_version": OV.PROFILE_SCHEMA_VERSION,
        "inline_region_sha256": _sha(region.encode("utf-8")),
        "cg_sdk_source": str(SDK_CG.relative_to(ROOT)), "cg_files": CG_FILES,
        "candidates": candidates,
        "all_candidates_ok": all(c["candidate_ok"] for c in candidates)
        and len(candidates) > 0,
        "guardrails": {
            "no_kaggle_upload": True, "no_github_push": True,
            "root_main_deck_untouched": True,
            "no_existing_tarball_mutation_or_deletion": True,
            "no_reference_agent_code_copied": True,
            "no_public_reference_as_source_or_parent": True,
            "no_online_search_in_hot_path": True,
        },
        "unsupported_claims": OV.unsupported_scorer_claims(),
        "built_at_epoch": int(time.time()),
    }


def main() -> int:
    rec = build()
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46h_candidate_build.json").write_text(
        json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46H (Part F) — Owned cg_typed per-option-value candidates", "",
        "_LOCAL benchmark-lane feasibility candidates. NOT a Kaggle score / leaderboard / "
        "strength claim. No upload, submit, push, root mutation, or EXISTING-tarball "
        "mutation. No public reference as source/parent. No online Search in the hot path. "
        "Card identity / target are visible-only heuristic labels — no exact-damage / "
        "lethal / KO / Boss-gust / spread / best-action / card-value claim._", "",
        f"- **candidates built:** {rec['n_candidates']} (max batch {rec['max_batch']})",
        f"- **source families:** {', '.join(rec['source_families'])}",
        f"- **build profiles:** {', '.join(rec['build_profile_ids'])}",
        f"- **scorer:** `{rec['scorer_source_module']}` "
        f"(schema {rec['scorer_schema_version']})",
        f"- **inline region sha256:** `{rec['inline_region_sha256']}`",
        f"- **all candidates ok:** **{rec['all_candidates_ok']}**", "",
        "## Candidates",
        "| candidate | parent (internal) | family | mode | bytes | deck✓ | byte-id | "
        "parity | static | ok |",
        "|---|---|---|---|---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for c in rec["candidates"]:
        md.append(
            f"| `{c['candidate_id']}` | `{c['parent_candidate_id']}` | "
            f"{c['parent_family']} | {c['scoring_mode']} | {c['tarball_bytes']} | "
            f"{'Y' if c['deck_unchanged'] and c['deck_rows'] == 60 else 'N'} | "
            f"{'Y' if c['inline_region_byte_identical'] else 'N'} | "
            f"{'Y' if c['parity']['behavioral_parity_ok'] else 'N'} | "
            f"{'Y' if c['cg_typed_static_pass'] else 'N'} | "
            f"{'Y' if c['candidate_ok'] else 'N'} |")
    if rec["skipped"]:
        md += ["", "## Skipped", ""]
        md += [f"- {s['family']}/{s['profile']}: {s['reason']}" for s in rec["skipped"]]
    (EXP / "pass46h_candidate_build.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"OK: built {rec['n_candidates']} candidates, "
          f"all_ok={rec['all_candidates_ok']}, skipped={len(rec['skipped'])}")
    return 0 if rec["all_candidates_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
