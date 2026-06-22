#!/usr/bin/env python3
"""PASS 46H (Part D) — per-OPTION feature + oracle-label dataset.
LOCAL / read-only.

REUSES the Pass-46F Part-C label dataset (``pass46f_turn_label_dataset.json``): the
oracle one-step scores per candidate option are taken AS-IS — the expensive Pass-46E
Search oracle is NOT re-run. For each labelled decision frame we RE-OPEN it from the
Pass-46C trace panel via ``search_oracle.build_search_inputs_from_frame`` so the option
indices line up EXACTLY with the rows' ``selected`` lists, then attach the Pass-46H
WITHIN-FAMILY per-OPTION VISIBLE features (resolved card identity + role, in-play target
area / energy count + target role, productive-alternatives) computed from
``option_value_features.extract_features``.

The 46C panel covers the WATER and LIGHTNING internal decks plus public references; the
Diamond build family does NOT appear in the panel, so its candidates transfer the SAME
deck-agnostic role-bucket priors (measured here on the available internal frames) via
Diamond's own role map — no Diamond-specific oracle calls and no per-deck overfitting.

A measurement role map is built OFFLINE over the UNION of card ids actually OBSERVED in
the frames (your hand / board / offered select list). This is a feature-extraction lookup
only; public-reference frames are benchmark INPUTS, never a source / parent / candidate.

Headline rows for downstream metrics are family-HOMOGENEOUS, SINGLE-INDEX, resolvable
options (the genuine within-family choices). Multi-index / unsupported / unresolvable
counts are retained honestly. Oracle scores are ASSUMPTION-BASED (fabricated hidden
zones); never exact. No exact-damage / lethal / missed-KO / Boss-gust / spread /
best-action claim. No mutation, no upload, no candidate generation, no events.

Writes data/experiments/pass46h_option_value_dataset.{json,md} and
pass46h_measurement_role_map.json. Importable: ``build_dataset() -> dict``.
"""
from __future__ import annotations

import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from ptcg_activegraph.analysis import option_value_features as OV  # noqa: E402
from ptcg_activegraph.analysis import search_oracle as O  # noqa: E402

EXP = REPO / "data" / "experiments"
TRACES = EXP / "pass46c_traces"
CARD_CSV = REPO / "data" / "cards" / "EN_Card_Data.csv"
F_LABELS = EXP / "pass46f_turn_label_dataset.json"

FEATURE_KEYS = ("bias", "family", "resolved_card_id", "resolved_roles",
                "target_card_id", "target_area", "target_energy_count",
                "target_roles", "productive_alternatives")


def _load_frame(trace: str, step: int, seat: int):
    path = TRACES / trace
    if not path.exists():
        return None
    try:
        data = json.loads(gzip.open(path).read())
    except Exception:
        return None
    steps = data.get("steps") or []
    if 0 <= step < len(steps) and 0 <= seat < len(steps[step]):
        return steps[step][seat]
    return None


def _select_and_board(frame):
    inp = O.build_search_inputs_from_frame(frame) if frame else None
    if not inp or not inp.get("ok"):
        return None, None
    obs = inp.get("observation") or {}
    return obs.get("select") or {}, obs.get("current") or {}


def build_dataset() -> dict:
    labels = json.loads(F_LABELS.read_text(encoding="utf-8"))
    rows_in = labels.get("rows") or []

    # group rows by decision frame, preserving order
    groups = defaultdict(list)
    for r in rows_in:
        groups[(r["trace"], r["step"], r["seat"])].append(r)

    # pass 1: reopen frames, attach raw option + provisional features (role-free)
    enriched = []  # (key, row, option_or_None, single_index)
    frame_cache = {}
    for key, rs in groups.items():
        trace, step, seat = key
        if key not in frame_cache:
            frame_cache[key] = _select_and_board(_load_frame(trace, step, seat))
        select, board = frame_cache[key]
        opts = []
        if isinstance(select, dict):
            o = select.get("option")
            opts = o if isinstance(o, list) else []
        for r in rs:
            sel = r.get("selected") or []
            single = len(sel) == 1
            option = None
            if single and isinstance(sel[0], int) and 0 <= sel[0] < len(opts):
                option = opts[sel[0]]
            enriched.append((key, r, option, single, select, board))

    # collect observed card ids (resolved + target) to build the union role map
    observed_ids = set()
    feats_cache = {}
    for idx, (key, r, option, single, select, board) in enumerate(enriched):
        if option is None:
            continue
        feats = OV.extract_features(option, select, board)
        feats_cache[idx] = feats
        for fk in ("resolved_card_id", "target_card_id"):
            cid = feats.get(fk)
            if isinstance(cid, int):
                observed_ids.add(cid)
    role_map = OV.build_deck_role_map(str(CARD_CSV), sorted(observed_ids))

    # pass 2: build output rows with role tokens attached
    out_rows = []
    group_meta = {}
    for key, rs in groups.items():
        fams = {r.get("candidate_family") for r in rs}
        homogeneous = len(fams) == 1
        # oracle-best option in the group (max oracle_score; tie -> lowest selected idx)
        best = None
        for r in rs:
            sel = r.get("selected") or []
            sc = r.get("oracle_score")
            si = sel[0] if (len(sel) == 1 and isinstance(sel[0], int)) else 10 ** 9
            cand = (float(sc) if isinstance(sc, (int, float)) else float("-inf"), -si)
            if best is None or cand > best[0]:
                best = (cand, sel)
        group_meta[key] = {
            "family": next(iter(fams)) if homogeneous else "mixed",
            "homogeneous": homogeneous,
            "n_options": len(rs),
            "oracle_best_selected": best[1] if best else None,
        }

    for idx, (key, r, option, single, select, board) in enumerate(enriched):
        feats = feats_cache.get(idx)
        bucket = r.get("role_bucket")
        is_internal = bucket == "internal_candidate"
        if feats is not None:
            rid = feats.get("resolved_card_id")
            tid = feats.get("target_card_id")
            resolved_roles = list(OV._role_tokens(role_map, rid))
            target_roles = list(OV._role_tokens(role_map, tid))
            resolvable = (rid is not None) or (feats.get("target_area") != "none")
            feat_row = {
                "family": feats.get("family"),
                "resolved_card_id": rid,
                "resolved_roles": resolved_roles,
                "target_card_id": tid,
                "target_area": feats.get("target_area"),
                "target_energy_count": feats.get("target_energy_count"),
                "target_roles": target_roles,
                "productive_alternatives": feats.get("productive_alternatives"),
            }
        else:
            resolvable = False
            feat_row = None
        gm = group_meta[key]
        out_rows.append({
            "trace": key[0], "step": key[1], "seat": key[2],
            "selected": r.get("selected"),
            "candidate_family": r.get("candidate_family"),
            "role_bucket": bucket,
            "is_internal": is_internal,
            "is_actual": r.get("is_actual"),
            "oracle_score": r.get("oracle_score"),
            "supported": r.get("supported"),
            "supported_level": r.get("supported_level"),
            "single_index": single,
            "resolvable": resolvable,
            "group_homogeneous": gm["homogeneous"],
            "group_n_options": gm["n_options"],
            "group_oracle_best_selected": gm["oracle_best_selected"],
            "features": feat_row,
        })

    # ---- coverage summary ----
    def _count(pred):
        return sum(1 for x in out_rows if pred(x))

    headline = [x for x in out_rows if x["group_homogeneous"] and x["single_index"]
                and x["resolvable"]]
    headline_internal = [x for x in headline if x["is_internal"]]
    by_family_internal = defaultdict(int)
    for x in headline_internal:
        by_family_internal[x["candidate_family"]] += 1
    headline_groups = {(x["trace"], x["step"], x["seat"]) for x in headline_internal}

    summary = {
        "pass": "46H", "part": "D_option_value_dataset",
        "local_only": True, "no_upload": True, "read_only": True,
        "production_mutated": False, "candidate_generated": False, "tick_executed": False,
        "source_label_dataset": "pass46f_turn_label_dataset",
        "oracle_reused_not_rerun": True,
        "n_groups": len(groups),
        "n_rows": len(out_rows),
        "n_supported": _count(lambda x: x["supported"]),
        "n_single_index": _count(lambda x: x["single_index"]),
        "n_resolvable": _count(lambda x: x["resolvable"]),
        "n_homogeneous_single_index_resolvable": len(headline),
        "n_headline_internal": len(headline_internal),
        "n_headline_internal_groups": len(headline_groups),
        "headline_internal_by_family": dict(sorted(by_family_internal.items())),
        "n_rows_internal": _count(lambda x: x["is_internal"]),
        "n_rows_public_ref": _count(lambda x: not x["is_internal"]),
        "measurement_role_map_card_ids": len(role_map),
        "feature_keys": list(FEATURE_KEYS),
        "caveats": [
            "READ-ONLY / LOCAL / DIAGNOSTIC: production Object Storage was not mutated.",
            "Oracle scores reused from Pass-46F (ASSUMPTION-BASED hidden zones); never exact.",
            "Card identity / target area read from YOUR visible board + offered menu only; "
            "no hidden hand / deck / prize contents.",
            "Role tokens are a COARSE deck-composition label; no card value / strength claim.",
            "Public-reference frames are benchmark INPUTS only; never a source / parent / "
            "candidate. Diamond is not in the panel; it transfers deck-agnostic priors.",
            "No exact-damage / lethal / missed-KO / Boss-gust / spread / best-action claim.",
        ],
        "unsupported_claims": OV.unsupported_scorer_claims(),
        "rows": out_rows,
    }

    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46h_option_value_dataset.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (EXP / "pass46h_measurement_role_map.json").write_text(
        json.dumps(role_map, indent=2, ensure_ascii=False), encoding="utf-8")

    md = [
        "# PASS 46H — Part D: Per-Option Feature + Oracle-Label Dataset", "",
        f"- Source labels: `{summary['source_label_dataset']}` (oracle REUSED, not re-run).",
        f"- Frames (groups): **{summary['n_groups']}**; option rows: **{summary['n_rows']}** "
        f"(internal {summary['n_rows_internal']} / public-ref {summary['n_rows_public_ref']}).",
        f"- Single-index: {summary['n_single_index']}; resolvable: {summary['n_resolvable']}.",
        f"- **Headline** (homogeneous + single-index + resolvable): "
        f"**{summary['n_homogeneous_single_index_resolvable']}** "
        f"(internal {summary['n_headline_internal']} across "
        f"{summary['n_headline_internal_groups']} frames).",
        f"- Headline internal by family: {summary['headline_internal_by_family']}.",
        f"- Measurement role map card ids: {summary['measurement_role_map_card_ids']}.",
        "", "## Caveats", "",
    ]
    md += [f"- {c}" for c in summary["caveats"]]
    (EXP / "pass46h_option_value_dataset.md").write_text("\n".join(md) + "\n",
                                                         encoding="utf-8")
    return summary


def main() -> int:
    s = build_dataset()
    print(f"OK: groups={s['n_groups']} rows={s['n_rows']} "
          f"headline={s['n_homogeneous_single_index_resolvable']} "
          f"(internal={s['n_headline_internal']} in {s['n_headline_internal_groups']} frames) "
          f"by_family={s['headline_internal_by_family']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
