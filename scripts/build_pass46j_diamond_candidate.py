#!/usr/bin/env python3
"""PASS 46J (Part E) — build the ONE owned cg_typed Diamond SPECIALIST PLANNER candidate.

Assembles a single ``cg_typed`` tarball whose top level is EXACTLY ``main.py`` +
``deck.csv`` + ``cg/``:

  - main.py  : an ORIGINAL deck-specific TURN PLANNER whose hot path is the VERBATIM
               ``diamond_specialist.py`` INLINE_DIAMOND_SPECIALIST_V0 region (no ``src/``
               import, NO online Search). The region computes a DiamondBoardView ->
               DiamondTurnPlan ONCE per decision and ranks the legal option indices in line
               with that shared plan. The Diamond role map + attacker priority are embedded
               INSIDE the region, so unlike the 46H flat scorers there is no external
               profile JSON — the planner is self-contained.
  - deck.csv : the internal parent deck ``diamond_toolbox_diancie``, copied BYTE-FOR-BYTE.
  - cg/      : the bundled SDK (allowed reference asset; NOT a reference AGENT).

The planner's single source of truth is
``src/ptcg_activegraph/analysis/diamond_specialist.py``; this generator embeds its INLINE
region verbatim. A parity check re-extracts the embedded region from the built tarball and
asserts it is BYTE-identical AND behaviourally identical to the repo module on fixtures.

HARD guardrails honoured: NO Kaggle upload/submit, NO GitHub push, NO root main.py/deck.csv
mutation, NO mutation/overwrite-with-different-bytes of any EXISTING tarball (output goes
to a NEW ``candidates_pass46j/`` dir), NO public reference as source/parent, NO reference
AGENT code copied. The parent deck/tarball is only READ. Output is an OWNED candidate
(public_reference=false, mutation_parent=internal). LOCAL only; no events, no promotion, no
queue, no registration. NOT a Kaggle score / leaderboard / strength claim.
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

from ptcg_activegraph.analysis import diamond_specialist as DS  # noqa: E402
from ptcg_activegraph.replays.fingerprints import deck_fingerprint  # noqa: E402

EXP = ROOT / "data" / "experiments"
SDK_CG = ROOT / "data" / "reference_agents" / "_sdk" / "cg"
SUBM = ROOT / "data" / "submissions"
PARENT_TARBALL = SUBM / "candidates_pass34" / "diamond_toolbox_diancie.tar.gz"
OUT_DIR = SUBM / "candidates_pass46j"
CG_FILES = ["__init__.py", "api.py", "game.py", "sim.py", "utils.py", "libcg.so"]
CAND_ID = "cg_typed_diamond_specialist_planner_v0"
PARENT_ID = "diamond_toolbox_diancie"


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
"""cg_typed candidate entrypoint — __CAND_ID__.

OWNED PASS-46J Diamond SPECIALIST TURN PLANNER. The hot path is the VERBATIM
``diamond_specialist.py`` INLINE_DIAMOND_SPECIALIST_V0 region: it builds a visible-only
DiamondBoardView, derives ONE coherent DiamondTurnPlan (phase, desired active role,
attacker/backup/energy targets, setup/search/discard intents, an attack_now gate, and
deck-out safety), then ranks the legal option indices IN LINE with that shared plan via
``choose_indices``. The Diamond role map + attacker priority are embedded inside the region;
there is NO external profile and NO online Search in this path. The deck is the internal
parent deck ``diamond_toolbox_diancie``, unchanged.

Card identity is resolved from the option's own area/index against YOUR visible hand or the
OFFERED select list; in-play targets are read from the option's inPlayArea/inPlayIndex over
YOUR own board. NO hidden hand / deck / prize contents are read. Role buckets are coarse
deck-composition labels; energy adequacy is judged by the VISIBLE attached-energy COUNT
only. NEITHER the plan nor any policy is a lethal / KO / missed-KO / exact-damage /
Boss-gust / spread / globally-best-action / card-value claim; the attack policy is a
heuristic gate only and never ranks attacks by damage (numeric attackId only).

No reference-agent policy code is copied; the only bundled reference asset is the ``cg``
SDK (allowed). Runtime contract: ``agent(obs_dict) -> list[int]`` of legal option indices
(or the 60 deck card ids on the deck-submission step). Never raises.

LOCAL benchmark-lane feasibility agent — NOT a Kaggle score / leaderboard / strength
claim. NO upload / submit / promote / mutate.
"""
from __future__ import annotations

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
_EMBEDDED_DECK = __EMBEDDED_DECK__


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
# Entrypoint — Diamond specialist turn planner over raw options (no online Search).
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

    # 1. Diamond specialist planner over the raw options (inlined, never-raise). The
    #    DiamondTurnPlan is built ONCE inside choose_indices and shared across contexts.
    try:
        board = obs_dict.get("current") if isinstance(obs_dict, dict) else None
        decision = choose_indices(select, board)
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


def build_main_py(region: str, deck_ids, cand_id: str) -> str:
    head = (_MAIN_HEAD
            .replace("__CAND_ID__", cand_id)
            .replace("__EMBEDDED_DECK__", repr(list(deck_ids))))
    return head + region.rstrip("\n") + "\n" + _MAIN_TAIL


def _extract_region(text: str) -> str:
    i = text.index(DS.INLINE_BEGIN_MARKER)
    j = text.index(DS.INLINE_END_MARKER) + len(DS.INLINE_END_MARKER)
    return text[i:j]


def _inner_members(tar_bytes: bytes) -> dict:
    """DECOMPRESSED member content keyed by archive name (gzip envelope ignored)."""
    out = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as t:
        for m in t.getmembers():
            if m.isfile():
                out[m.name] = t.extractfile(m).read()
    return out


# Parity fixtures spanning the planner contexts + malformed inputs.
def _parity_cases():
    deck40 = [{"id": 5}] * 40
    cases = [
        ({"minCount": 1, "maxCount": 1, "option": [
            {"type": 7, "area": 2, "index": 0}, {"type": 7, "area": 2, "index": 1},
            {"type": 12}]},
         {"turn": 1, "yourIndex": 0, "players": [
             {"hand": [{"id": 525}, {"id": 766}, {"id": 5}], "deck": deck40,
              "bench": [], "prizes": [0] * 6}, {"hand": [0] * 5, "deck": deck40}]}),
        ({"minCount": 1, "maxCount": 1, "deck": [{"id": 1224}, {"id": 766}, {"id": 5}],
          "option": [{"type": 3, "area": 1, "index": 0},
                     {"type": 3, "area": 1, "index": 1},
                     {"type": 3, "area": 1, "index": 2}]},
         {"turn": 2, "yourIndex": 0, "players": [
             {"hand": [0] * 3, "deck": deck40, "bench": [{"id": 767}],
              "active": [{"id": 525}]}, {"hand": [0] * 4, "deck": deck40}]}),
        ({"minCount": 1, "maxCount": 1, "option": [
            {"type": 12}, {"type": 13, "attackId": 0},
            {"type": 8, "inPlayArea": 4, "inPlayIndex": 0}]},
         {"turn": 4, "yourIndex": 0, "players": [
             {"hand": [0] * 3, "deck": deck40, "bench": [{"id": 525}],
              "active": [{"id": 766, "energyCards": [0, 0, 0]}]},
             {"hand": [0] * 4, "deck": deck40, "active": [{"id": 99}]}]}),
        ({"minCount": 2, "maxCount": 2, "option": [
            {"type": 7, "area": 2, "index": 0}, {"type": 7, "area": 2, "index": 1},
            {"type": 7, "area": 2, "index": 2}]},
         {"turn": 1, "yourIndex": 0, "players": [
             {"hand": [{"id": 183}, {"id": 1224}, {"id": 767}], "deck": deck40,
              "bench": [], "active": [{"id": 525}]}, {"hand": [0] * 5, "deck": deck40}]}),
        ({"minCount": 1, "maxCount": 1, "option": [
            {"type": 3, "area": 2, "index": 0}, {"type": 3, "area": 2, "index": 1}]},
         {"turn": 3, "yourIndex": 0, "players": [
             {"hand": [{"id": 434}, {"id": 766}], "deck": deck40,
              "active": [{"id": 766, "energyCards": [0, 0]}]},
             {"hand": [0] * 4, "deck": deck40}]}),
        ({"option": [{"type": 0}], "minCount": 0, "maxCount": 0}, None),
        ({"option": [{"type": 99}, {"type": 14}], "minCount": 1, "maxCount": 1}, None),
        ("garbage-not-a-dict", {"players": "bad"}),
        ({"option": None}, None),
    ]
    return cases


def _behavioral_parity(region: str) -> dict:
    ns: dict = {}
    exec(region, ns)  # noqa: S102 - trusted, self-built region
    ci, bv, tp, so = [], [], [], []
    for sel, board in _parity_cases():
        a = DS.choose_indices(sel, board)
        b = ns["choose_indices"](sel, board)
        if a != b:
            ci.append({"select": sel, "board": board, "repo": a, "inlined": b})
        va = DS.make_board_view(sel, board)
        vb = ns["make_board_view"](sel, board)
        if va != vb:
            bv.append({"select": sel, "board": board})
        ta = DS.make_turn_plan(va)
        tb = ns["make_turn_plan"](va)
        if ta != tb:
            tp.append({"select": sel, "board": board})
        sa = DS.score_options_from_plan(sel, board, ta)
        sb = ns["score_options_from_plan"](sel, board, ta)
        if sa != sb:
            so.append({"select": sel, "board": board})
    return {"choose_indices_mismatches": ci, "board_view_mismatches": bv,
            "turn_plan_mismatches": tp, "score_options_mismatches": so,
            "behavioral_parity_ok": not (ci or bv or tp or so)}


def _read_parent_deck(tarball: Path):
    with tarfile.open(tarball, "r:gz") as st:
        deck_bytes = st.extractfile("deck.csv").read()
    deck_ids = [int(x) for x in deck_bytes.decode("utf-8").split() if x.strip()]
    return deck_bytes, deck_ids


def run_validator(tarball: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate_cg_typed_tarball.py"),
         str(tarball), "--import-smoke"],
        capture_output=True, text=True)
    return {"returncode": proc.returncode, "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip()}


def build() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for req in (PARENT_TARBALL, SDK_CG):
        if not req.exists():
            raise SystemExit(f"missing required input: {req}")

    region = DS.inline_region_text()
    if not region or "INLINE_DIAMOND_SPECIALIST_V0_BEGIN" not in region:
        raise SystemExit("could not extract INLINE_DIAMOND_SPECIALIST_V0 region")

    deck_bytes, deck_ids = _read_parent_deck(PARENT_TARBALL)
    if len(deck_ids) != 60:
        raise SystemExit(f"parent deck has {len(deck_ids)} rows, expected 60")

    cg_members = []
    for fn in CG_FILES:
        fp = SDK_CG / fn
        if not fp.is_file():
            raise SystemExit(f"missing cg SDK file: {fp}")
        cg_members.append((f"cg/{fn}", fp.read_bytes()))

    main_src = build_main_py(region, deck_ids, CAND_ID)
    main_bytes = main_src.encode("utf-8")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=9) as tar:
        _add_bytes(tar, "main.py", main_bytes)
        _add_bytes(tar, "deck.csv", deck_bytes)
        for arc, data in cg_members:
            _add_bytes(tar, arc, data, mode=(0o755 if arc.endswith(".so") else 0o644))
    fresh_tar_bytes = buf.getvalue()
    intended_members = _inner_members(fresh_tar_bytes)

    out_tar = OUT_DIR / f"{CAND_ID}.tar.gz"
    if OUT_DIR.resolve() not in out_tar.resolve().parents:
        raise SystemExit(f"refusing to write outside {OUT_DIR}: {out_tar}")
    # Idempotent + fail-closed. The gzip envelope embeds a timestamp so it is NOT
    # reproducible; comparing raw bytes would wrongly reject an identical re-build. So
    # compare the DECOMPRESSED member content: accept an existing artifact when every
    # member is byte-identical (never overwrite/delete it), and refuse only when the inner
    # CONTENT differs. The reported sha/size are always of the artifact actually on disk.
    if out_tar.exists():
        existing_members = _inner_members(out_tar.read_bytes())
        if existing_members != intended_members:
            raise SystemExit(
                f"refusing to overwrite existing tarball with different content: {out_tar}")
    else:
        out_tar.write_bytes(fresh_tar_bytes)
    tar_on_disk = out_tar.read_bytes()

    with tarfile.open(out_tar, "r:gz") as tar:
        names = [m.name for m in tar.getmembers() if m.isfile()]
        extracted_main = tar.extractfile("main.py").read().decode("utf-8")
    top = sorted({n.split("/", 1)[0] for n in names})
    assert top == ["cg", "deck.csv", "main.py"], f"unexpected top-level: {top}"
    assert not any("__pycache__" in n for n in names), "pycache leaked"

    embedded_region = _extract_region(extracted_main)
    region_byte_identical = (embedded_region == region)
    parity = _behavioral_parity(embedded_region)

    # Line-based (not substring): the module path may appear in provenance comments; only an
    # actual ``import``/``from ... import`` line referencing src would be a real src import.
    src_import_lines = [
        ln.strip() for ln in extracted_main.splitlines()
        if ln.strip().startswith(("import ", "from "))
        and ("ptcg_activegraph" in ln or "src." in ln)]
    no_src_import = not src_import_lines
    cg_imported = ("from cg import api" in extracted_main)

    rec = {
        "pass": "46j", "part": "E", "read_only": False, "local_only": True,
        "no_upload": True, "production_mutated": False, "candidate_generated": True,
        "lane": "cg_typed", "candidate_id": CAND_ID,
        "is_planner_not_flat_scorer": True,
        "tarball": str(out_tar.relative_to(ROOT)), "tarball_sha256": _sha(tar_on_disk),
        "tarball_bytes": len(tar_on_disk),
        "owned_candidate": True, "public_reference": False,
        "mutation_parent": "internal", "parent_candidate_id": PARENT_ID,
        "parent_source_tarball": str(PARENT_TARBALL.relative_to(ROOT)),
        "deck_unchanged": True, "deck_sha256": _sha(deck_bytes), "deck_rows": len(deck_ids),
        "deck_fingerprint": deck_fingerprint(deck_ids),
        "main_py_sha256": _sha(main_bytes), "main_py_bytes": len(main_bytes),
        "planner_source_module":
            "src/ptcg_activegraph/analysis/diamond_specialist.py",
        "role_map_entries": len(DS.DIAMOND_ROLE_MAP),
        "main_attacker_id": DS.MAIN_ATTACKER_ID,
        "attacker_priority": list(DS.ATTACKER_PRIORITY),
        "no_online_search": True,
        "no_src_import": no_src_import, "cg_imported": cg_imported,
        "inline_region_byte_identical": region_byte_identical,
        "inline_region_sha256": _sha(region.encode("utf-8")),
        "parity": parity,
        "members": sorted(names), "top_level": top,
        "cg_sdk_source": str(SDK_CG.relative_to(ROOT)), "cg_files": CG_FILES,
        "unsupported_claims": list(DS.unsupported_claims()),
        "guardrails": {
            "no_kaggle_upload": True, "no_github_push": True,
            "root_main_deck_untouched": True,
            "no_existing_tarball_mutation_or_deletion": True,
            "no_reference_agent_code_copied": True,
            "no_public_reference_as_source_or_parent": True,
            "no_online_search_in_hot_path": True,
        },
        "built_at_epoch": int(time.time()),
    }
    rec["cg_typed_validator"] = run_validator(out_tar)
    rec["cg_typed_static_pass"] = (rec["cg_typed_validator"]["returncode"] == 0)
    rec["candidate_ok"] = bool(
        rec["cg_typed_static_pass"] and region_byte_identical
        and parity["behavioral_parity_ok"] and rec["deck_unchanged"]
        and rec["deck_rows"] == 60 and no_src_import and cg_imported)
    return rec


def _write_md(rec: dict) -> None:
    p = rec["parity"]
    lines = [
        "# PASS 46J · Part E — Owned cg_typed Diamond Specialist Planner candidate", "",
        "_LOCAL benchmark-lane feasibility candidate. NOT a Kaggle score / leaderboard / "
        "strength claim. No upload, submit, push, root mutation, or EXISTING-tarball "
        "mutation. No public reference as source/parent. No online Search in the hot path. "
        "The planner is visible-only and asserts no exact-damage / lethal / KO / Boss-gust "
        "/ spread / best-action claim._", "",
        f"**candidate_ok:** {'✅' if rec['candidate_ok'] else '❌'}  ·  "
        f"candidate_id: `{rec['candidate_id']}`", "",
        "## Tarball",
        f"- path: `{rec['tarball']}` ({rec['tarball_bytes']} bytes)",
        f"- top-level: {rec['top_level']}  ·  members: {len(rec['members'])}",
        f"- sha256: `{rec['tarball_sha256'][:16]}…`", "",
        "## Provenance",
        f"- owned_candidate: {rec['owned_candidate']}  ·  public_reference: "
        f"{rec['public_reference']}  ·  mutation_parent: {rec['mutation_parent']}",
        f"- parent: `{rec['parent_candidate_id']}` "
        f"(source `{rec['parent_source_tarball']}`)",
        f"- deck_unchanged: {rec['deck_unchanged']}  ·  deck_rows: {rec['deck_rows']}  ·  "
        f"deck_sha256: `{rec['deck_sha256'][:16]}…`", "",
        "## Planner integrity",
        f"- source module: `{rec['planner_source_module']}`",
        f"- is_planner_not_flat_scorer: {rec['is_planner_not_flat_scorer']}  ·  "
        f"role_map_entries: {rec['role_map_entries']}  ·  "
        f"main_attacker: {rec['main_attacker_id']}",
        f"- inline_region_byte_identical: **{rec['inline_region_byte_identical']}**",
        f"- behavioral_parity_ok: **{p['behavioral_parity_ok']}** "
        f"(choose_indices={len(p['choose_indices_mismatches'])}, "
        f"board_view={len(p['board_view_mismatches'])}, "
        f"turn_plan={len(p['turn_plan_mismatches'])}, "
        f"score_options={len(p['score_options_mismatches'])} mismatches)",
        f"- no_src_import: {rec['no_src_import']}  ·  cg_imported: {rec['cg_imported']}  ·  "
        f"no_online_search: {rec['no_online_search']}", "",
        "## cg_typed validator",
        f"- returncode: {rec['cg_typed_validator']['returncode']}  ·  static_pass: "
        f"{rec['cg_typed_static_pass']}", "",
        "## Unsupported claims (hard honesty boundary)",
        f"- {', '.join(rec['unsupported_claims'])}", "",
    ]
    (EXP / "pass46j_candidate_build.md").write_text("\n".join(lines) + "\n",
                                                    encoding="utf-8")


def main() -> int:
    rec = build()
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46j_candidate_build.json").write_text(
        json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")
    _write_md(rec)
    print(json.dumps({
        "candidate_ok": rec["candidate_ok"],
        "tarball": rec["tarball"],
        "inline_region_byte_identical": rec["inline_region_byte_identical"],
        "behavioral_parity_ok": rec["parity"]["behavioral_parity_ok"],
        "cg_typed_static_pass": rec["cg_typed_static_pass"],
        "no_src_import": rec["no_src_import"], "cg_imported": rec["cg_imported"],
        "deck_rows": rec["deck_rows"],
    }, indent=2))
    return 0 if rec["candidate_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
