#!/usr/bin/env python3
"""PASS 46G (Part D) — offline MEASUREMENT of each profile vs the search oracle.

REUSES the Pass-46F Part-C label dataset (``pass46f_turn_label_dataset.json``): the
oracle one-step scores per candidate action are taken as-is — the (expensive) Pass-46E
Search oracle is NOT re-run. For phase/role context (which the 46F rows do not carry)
each labelled decision frame is RE-OPENED from the Pass-46C trace panel and rebuilt
through ``search_oracle.build_search_inputs_from_frame`` so the candidate option
indices line up EXACTLY with the rows' ``selected`` lists, while phase/role are read
from the REAL recorded own-board.

For every catalog profile we then, on the SAME frames, pick the highest-scoring
candidate action and compare against the oracle:

* **oracle top-1 agreement** — how often the profile's pick is the candidate with the
  highest oracle one-step score (tie-broken deterministically).
* **mean/median oracle-score lift vs baseline ``generic_progress_v0``** — the charter
  comparison. Also decomposed against ``search_seeded_family_only_v1`` to separate the
  value of better FAMILY weights from the value of the PHASE/ROLE layer.
* **end/pass reduction on productive frames** — among frames where ending the turn AND
  a productive action are both available, how much LESS often the profile ends the turn
  than the baseline.
* **attach / search reasonability** — when an attach (or search) action is available,
  how often the profile picks it (a sanity check that energy/search logic is sane).

This is an IN-SAMPLE OFFLINE FIT measurement ONLY. It is NOT a win-rate, generalization,
or strength claim — real gameplay is screened in Parts G/H. Oracle scores are
ASSUMPTION-BASED (fabricated hidden zones); never exact. No exact-damage / lethal /
missed-KO / Boss-gust / spread / best-action claim.

LOCAL / READ-ONLY. No mutation, no upload, no candidate generation, no events.
Runnable standalone and importable (``run_calibration() -> dict``).
"""
from __future__ import annotations

import glob
import gzip
import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.analysis import search_oracle as O  # noqa: E402
from ptcg_activegraph.analysis import turn_planner_profiles as TP  # noqa: E402

EXP = REPO / "data" / "experiments"
TRACES = EXP / "pass46c_traces"
LABELS = EXP / "pass46f_turn_label_dataset.json"
CATALOG = EXP / "pass46g_profile_catalog.json"

BASELINE_ID = "generic_progress_v0"
FAMILY_REF_ID = "search_seeded_family_only_v1"

CAVEATS = [
    "READ-ONLY / LOCAL: production Object Storage was not mutated; no tick / upload / "
    "candidate generation / events.",
    "Oracle scores are REUSED from Pass-46F (NOT re-run) and are ASSUMPTION-BASED "
    "(fabricated hidden zones); never exact.",
    "IN-SAMPLE OFFLINE FIT only on the calibration frames — NOT a win-rate, "
    "generalization, or strength claim. Real gameplay is screened in Parts G/H.",
    "Measurement is over the bounded oracle-scored candidate subset per frame "
    "(the 46F label rows), not over every conceivable line.",
    "phase is a coarse OBSERVABLE label; role is a target-AREA label. No exact-damage "
    "/ lethal / missed-KO / Boss-gust / spread / best-action claim.",
]


class _TraceCache:
    def __init__(self):
        self._d = {}

    def frame(self, trace_name, step, seat):
        d = self._d.get(trace_name)
        if d is None:
            p = TRACES / trace_name
            if not p.exists():
                self._d[trace_name] = False
                return None
            try:
                d = json.loads(gzip.open(p).read())
            except Exception:
                d = False
            self._d[trace_name] = d
        if not d:
            return None
        steps = d.get("steps") or []
        if not (isinstance(step, int) and 0 <= step < len(steps)):
            return None
        st = steps[step]
        if not (isinstance(st, list) and isinstance(seat, int) and 0 <= seat < len(st)):
            return None
        return st[seat]


def _candidate_profile_score(selected, options, select, board, profile) -> float:
    total = 0.0
    n = len(options)
    for i in selected:
        if isinstance(i, int) and 0 <= i < n:
            total += TP.score_option(
                TP.extract_features(options[i], select, board), profile)
    return total


def _pick(cands, score_key):
    """cands: list of dicts with 'selected','oracle_score',(score_key). Pick max
    score_key, tie-broken by lexicographically smallest 'selected'."""
    best = None
    for c in cands:
        key = (c[score_key], tuple(-x for x in c["selected"]))
        if best is None or key > best[0]:
            best = (key, c)
    return best[1] if best else None


def _ms(xs):
    return {"n": len(xs),
            "mean": round(statistics.fmean(xs), 4) if xs else None,
            "median": round(statistics.median(xs), 4) if xs else None}


def run_calibration() -> dict:
    for req in (LABELS, CATALOG):
        if not req.exists():
            raise SystemExit(f"missing required input: {req} (run prior parts first)")
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    profiles = catalog["profiles"]

    # ---- Reassemble per-frame candidate sets with phase/role context ----
    cache = _TraceCache()
    by_frame: dict[tuple, dict] = {}
    n_rows = 0
    n_supported = 0
    n_frames_with_ctx = 0
    n_frames_no_ctx = 0
    for r in labels.get("rows") or []:
        n_rows += 1
        if not r.get("supported"):
            continue
        n_supported += 1
        key = (r.get("trace"), r.get("step"), r.get("seat"))
        fr = by_frame.get(key)
        if fr is None:
            frame = cache.frame(*key)
            ctx = None
            if frame is not None:
                inp = O.build_search_inputs_from_frame(frame)
                if inp_ok := inp_ctx(inp):
                    ctx = inp_ok
            fr = {"ctx": ctx, "cands": []}
            by_frame[key] = fr
        fr["cands"].append({
            "selected": list(r.get("selected") or []),
            "oracle_score": float(r.get("oracle_score") or 0.0),
            "candidate_family": r.get("candidate_family", "unknown"),
        })

    # ---- Per-profile measurement over frames that have context + >=2 candidates ----
    profile_ids = list(profiles.keys())
    results = {pid: {
        "pick_oracle_scores": [], "pick_oracle_scores_familychoice": [],
        "agree_oracle_top1": 0, "n_eval": 0, "n_familychoice": 0,
        "agree_oracle_top1_familychoice": 0,
        "pick_family_counts": {}, "end_picks_productive": 0,
        "attach_avail": 0, "attach_picked": 0,
        "search_avail": 0, "search_picked": 0,
    } for pid in profile_ids}
    productive_frames = 0

    for key, fr in by_frame.items():
        ctx = fr["ctx"]
        cands = fr["cands"]
        if ctx is None:
            n_frames_no_ctx += 1
            continue
        n_frames_with_ctx += 1
        if len(cands) < 2:
            continue
        options, select, board = ctx["options"], ctx["select"], ctx["board"]
        distinct_fams = {c["candidate_family"] for c in cands}
        is_familychoice = len(distinct_fams) >= 2
        fams_present = {TP.family_for_option(options[c["selected"][0]])
                       if c["selected"] and 0 <= c["selected"][0] < len(options)
                       else "unknown" for c in cands}
        attach_here = "attach_energy" in fams_present
        search_here = "select_card" in fams_present
        end_here = "end_turn" in fams_present
        productive_here = end_here and any(f != "end_turn" for f in fams_present)
        if productive_here:
            productive_frames += 1

        # oracle-best candidate for this frame (tie-broken deterministically)
        oracle_best = _pick(cands, "oracle_score")

        for pid in profile_ids:
            prof = profiles[pid]
            scored = []
            for c in cands:
                sc = _candidate_profile_score(
                    c["selected"], options, select, board, prof)
                scored.append({**c, "pscore": sc})
            pick = _pick(scored, "pscore")
            if pick is None:
                continue
            R = results[pid]
            R["n_eval"] += 1
            R["pick_oracle_scores"].append(pick["oracle_score"])
            pf = TP.family_for_option(options[pick["selected"][0]]) \
                if pick["selected"] and 0 <= pick["selected"][0] < len(options) \
                else "unknown"
            R["pick_family_counts"][pf] = R["pick_family_counts"].get(pf, 0) + 1
            if oracle_best is not None and pick["selected"] == oracle_best["selected"]:
                R["agree_oracle_top1"] += 1
            if is_familychoice:
                R["n_familychoice"] += 1
                R["pick_oracle_scores_familychoice"].append(pick["oracle_score"])
                if oracle_best is not None and \
                        pick["selected"] == oracle_best["selected"]:
                    R["agree_oracle_top1_familychoice"] += 1
            if productive_here and pf == "end_turn":
                R["end_picks_productive"] += 1
            if attach_here:
                R["attach_avail"] += 1
                if pf == "attach_energy":
                    R["attach_picked"] += 1
            if search_here:
                R["search_avail"] += 1
                if pf == "select_card":
                    R["search_picked"] += 1

    # ---- Summaries + lift vs baselines ----
    def _summ(pid):
        R = results[pid]
        ms = _ms(R["pick_oracle_scores"])
        msf = _ms(R["pick_oracle_scores_familychoice"])
        return {
            "n_eval_frames": R["n_eval"],
            "n_familychoice_frames": R["n_familychoice"],
            "oracle_top1_agreement": round(R["agree_oracle_top1"] / R["n_eval"], 4)
            if R["n_eval"] else None,
            "oracle_top1_agreement_familychoice":
                round(R["agree_oracle_top1_familychoice"] / R["n_familychoice"], 4)
                if R["n_familychoice"] else None,
            "pick_oracle_score": ms,
            "pick_oracle_score_familychoice": msf,
            "pick_family_counts": dict(sorted(R["pick_family_counts"].items())),
            "end_pick_rate_productive":
                round(R["end_picks_productive"] / productive_frames, 4)
                if productive_frames else None,
            "attach_pick_rate_when_available":
                round(R["attach_picked"] / R["attach_avail"], 4)
                if R["attach_avail"] else None,
            "search_pick_rate_when_available":
                round(R["search_picked"] / R["search_avail"], 4)
                if R["search_avail"] else None,
        }

    summaries = {pid: _summ(pid) for pid in profile_ids}
    base = summaries.get(BASELINE_ID, {})
    fam_ref = summaries.get(FAMILY_REF_ID, {})

    def _lift(a, b, field):
        av = (summaries[a].get(field) or {}).get("median")
        bv = (summaries[b].get(field) or {}).get("median")
        am = (summaries[a].get(field) or {}).get("mean")
        bm = (summaries[b].get(field) or {}).get("mean")
        return {
            "median_lift": round((av or 0) - (bv or 0), 4)
            if av is not None and bv is not None else None,
            "mean_lift": round((am or 0) - (bm or 0), 4)
            if am is not None and bm is not None else None,
        }

    measured = {}
    for pid in profile_ids:
        s = summaries[pid]
        end_red = None
        if (base.get("end_pick_rate_productive") is not None
                and s.get("end_pick_rate_productive") is not None):
            end_red = round(base["end_pick_rate_productive"]
                            - s["end_pick_rate_productive"], 4)
        measured[pid] = {
            **s,
            "role": profiles[pid].get("role"),
            "lift_vs_baseline_generic": _lift(pid, BASELINE_ID,
                                              "pick_oracle_score"),
            "lift_vs_family_only_ref": _lift(pid, FAMILY_REF_ID,
                                             "pick_oracle_score"),
            "end_pass_reduction_vs_baseline": end_red,
        }

    # ---- Collapse diagnostics (WHY the phase/role layer is ~inert) ----
    def _rank(prof, cands, options, select, board):
        scored = [
            (_candidate_profile_score(c["selected"], options, select, board, prof),
             tuple(-x for x in c["selected"]), idx)
            for idx, c in enumerate(cands)]
        return sorted(range(len(cands)), key=lambda j: scored[j], reverse=True)

    phase_distribution: dict = {}
    menu_family_sets: dict = {}
    attack_attach_cooccur = 0
    n_multi = 0
    rank_diff = {pid: {"argmax_diff": 0, "full_rank_diff": 0} for pid in profile_ids}
    fam_ref_prof = profiles[FAMILY_REF_ID]
    for key, fr in by_frame.items():
        ctx = fr["ctx"]
        if ctx is None:
            continue
        options, select, board = ctx["options"], ctx["select"], ctx["board"]
        ph = TP.detect_phase(select, board)
        phase_distribution[ph] = phase_distribution.get(ph, 0) + 1
        cands = fr["cands"]
        fams = {TP.family_for_option(options[c["selected"][0]])
                for c in cands
                if c["selected"] and 0 <= c["selected"][0] < len(options)}
        fkey = ",".join(sorted(fams)) or "(none)"
        menu_family_sets[fkey] = menu_family_sets.get(fkey, 0) + 1
        if "attack" in fams and "attach_energy" in fams:
            attack_attach_cooccur += 1
        if len(cands) < 2:
            continue
        n_multi += 1
        base_order = _rank(fam_ref_prof, cands, options, select, board)
        for pid in profile_ids:
            o2 = _rank(profiles[pid], cands, options, select, board)
            if o2[0] != base_order[0]:
                rank_diff[pid]["argmax_diff"] += 1
            if o2 != base_order:
                rank_diff[pid]["full_rank_diff"] += 1

    collapse_diagnostics = {
        "reference_profile_id": FAMILY_REF_ID,
        "n_multi_candidate_frames": n_multi,
        "phase_distribution": dict(sorted(phase_distribution.items())),
        "menu_candidate_family_sets": dict(sorted(menu_family_sets.items(),
                                                  key=lambda kv: -kv[1])),
        "attack_attach_cooccurrence_frames": attack_attach_cooccur,
        "rank_diff_vs_family_only": rank_diff,
        "phase_role_layer_offline_top1_inert": all(
            rank_diff[pid]["argmax_diff"] == 0 for pid in profile_ids
            if profiles[pid].get("role") in ("candidate", "expansion")),
        "interpretation": (
            "argmax_diff = # multi-candidate frames where the profile's top-1 pick "
            "differs from the family-only reference; full_rank_diff = # frames where "
            "any rank position differs. The phase/role layer is offline top-1-inert "
            "wherever argmax_diff == 0. Root cause: cg select menus are largely "
            "family-homogeneous or pair non-competing families (attack & attach_energy "
            "never co-occur), so cross-family phase boosts have no competing "
            "higher-weight family to flip, and within-family role reweighting rarely "
            "displaces the top oracle pick."),
    }

    data = {
        "pass": "46g", "part": "D", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "candidate_generated": False,
        "oracle_rerun": False, "reused_label_dataset": LABELS.name,
        "scorer_schema_version": TP.PROFILE_SCHEMA_VERSION,
        "baseline_profile_id": BASELINE_ID, "family_reference_id": FAMILY_REF_ID,
        "n_label_rows": n_rows, "n_supported_rows": n_supported,
        "n_frames_total": len(by_frame),
        "n_frames_with_context": n_frames_with_ctx,
        "n_frames_without_context": n_frames_no_ctx,
        "n_productive_frames": productive_frames,
        "measured_profiles": measured,
        "collapse_diagnostics": collapse_diagnostics,
        "caveats": CAVEATS,
        "unsupported_claims": {**O.unsupported_search_claims(),
                               **TP.unsupported_scorer_claims()},
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46g_profile_calibration.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46G — Part D: offline profile measurement vs the search oracle", "",
        "_REUSES the Pass-46F oracle labels (NOT re-run). IN-SAMPLE OFFLINE FIT only — "
        "NOT a win-rate / generalization / strength claim. Oracle scores are "
        "assumption-based; never exact. No exact-damage / lethal / Boss / gust / "
        "spread / best-action claim. LOCAL / READ-ONLY; no generation / upload / "
        "events._", "",
        "## Caveats"] + [f"- {c}" for c in CAVEATS] + [
        "", "## Frames",
        f"- supported label rows: **{n_supported}** / {n_rows}",
        f"- decision frames: **{len(by_frame)}** "
        f"(with context: {n_frames_with_ctx}, without: {n_frames_no_ctx})",
        f"- productive frames (end + productive both available): "
        f"**{productive_frames}**", "",
        "## Per-profile offline fit",
        "| profile | role | n | oracle top-1 | top-1 (fam-choice) | pick median | "
        "median lift vs generic | median lift vs family-only | end-rate (prod) | "
        "end reduction | attach pick | search pick |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for pid in profile_ids:
        m = measured[pid]
        md.append(
            f"| `{pid}` | {m['role']} | {m['n_eval_frames']} | "
            f"{m['oracle_top1_agreement']} | "
            f"{m['oracle_top1_agreement_familychoice']} | "
            f"{(m['pick_oracle_score'] or {}).get('median')} | "
            f"{m['lift_vs_baseline_generic']['median_lift']} | "
            f"{m['lift_vs_family_only_ref']['median_lift']} | "
            f"{m['end_pick_rate_productive']} | "
            f"{m['end_pass_reduction_vs_baseline']} | "
            f"{m['attach_pick_rate_when_available']} | "
            f"{m['search_pick_rate_when_available']} |")
    md += ["", "## Pick family distribution (per profile)"]
    for pid in profile_ids:
        md.append(f"- `{pid}`: {measured[pid]['pick_family_counts']}")
    cd = collapse_diagnostics
    md += [
        "", "## Collapse diagnostics — why the phase/role layer is ~inert",
        f"_{cd['interpretation']}_", "",
        f"- phase/role layer offline top-1 inert: "
        f"**{cd['phase_role_layer_offline_top1_inert']}**",
        f"- multi-candidate frames: {cd['n_multi_candidate_frames']}",
        f"- attack & attach_energy co-occur in the same menu: "
        f"**{cd['attack_attach_cooccurrence_frames']}** frames",
        f"- phase distribution: {cd['phase_distribution']}", "",
        "### Top-1 / full-rank changes vs family-only reference "
        f"(`{cd['reference_profile_id']}`)",
        "| profile | argmax_diff | full_rank_diff |", "|---|---:|---:|",
    ]
    for pid in profile_ids:
        rd = cd["rank_diff_vs_family_only"][pid]
        md.append(f"| `{pid}` | {rd['argmax_diff']} | {rd['full_rank_diff']} |")
    md += ["", "### Menu candidate-family sets (count)",
           "| families present in menu | frames |", "|---|---:|"]
    for fkey, n in cd["menu_candidate_family_sets"].items():
        md.append(f"| {fkey} | {n} |")
    (EXP / "pass46g_profile_calibration.md").write_text("\n".join(md) + "\n",
                                                        encoding="utf-8")

    print(json.dumps({
        "n_supported_rows": n_supported, "n_frames": len(by_frame),
        "n_frames_with_context": n_frames_with_ctx,
        "n_productive_frames": productive_frames,
        "summary": {pid: {
            "oracle_top1": measured[pid]["oracle_top1_agreement"],
            "median_lift_vs_generic":
                measured[pid]["lift_vs_baseline_generic"]["median_lift"],
            "end_reduction": measured[pid]["end_pass_reduction_vs_baseline"],
        } for pid in profile_ids},
    }, indent=2, default=str))
    return data


def inp_ctx(inp: dict):
    """Return scoring context from a build_search_inputs result, or None."""
    if not inp or not inp.get("ok"):
        return None
    obs = inp.get("observation")
    if not isinstance(obs, dict):
        return None
    select = obs.get("select")
    board = obs.get("current")
    if not isinstance(select, dict):
        return None
    options = select.get("option") or []
    if not isinstance(options, list) or not options:
        return None
    return {"options": options, "select": select, "board": board}


if __name__ == "__main__":
    run_calibration()
