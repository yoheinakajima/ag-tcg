#!/usr/bin/env python3
"""PASS 46F (Part G.1) — decision-trace NON-INERTNESS audit vs the parent.

Deterministic (NO game execution): replays the SOURCE/parent's own ACTIVE-seat
decision frames (from the Pass-46C trace panel) through the BUILT candidate's
actual ``agent()`` and reports how the calibrated fast scorer behaves relative to
the parent's recorded choices:

  - non-inertness    : fraction of frames where the candidate picks a DIFFERENT
                       option-set than the parent did (a degenerate "always copy"
                       or "always index 0 / always end-turn" policy would score ~0
                       changed AND a collapsed family histogram);
  - safety           : every candidate decision is LEGAL (in-range, min/max
                       honoured) and NEVER raises;
  - fallback usage   : how often the inlined scorer declined (empty) and the legal
                       fallback supplied the action.

This measures that the policy is *active and safe*, NOT that it is *stronger*
(strength is the Part-H eval panel's job). HONEST: non-inertness is necessary, not
sufficient. No exact-damage / lethal / missed-KO / Boss-gust / spread / best-action
claim. LOCAL / READ-ONLY: no Object Storage, no tick, no events, no upload.

The candidate's ``agent()`` is executed in a HARD-TIMEOUT SUBPROCESS (native cg can
wedge). Writes data/experiments/pass46f_non_inertness.{json,md}.
"""
from __future__ import annotations

import glob
import gzip
import json
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.analysis import search_oracle as O  # noqa: E402
from ptcg_activegraph.analysis import turn_scorer as TS  # noqa: E402
from ptcg_activegraph.tournament.artifacts import safe_extract_all  # noqa: E402

EXP = REPO / "data" / "experiments"
TRACES = EXP / "pass46c_traces"
SOURCE_JSON = EXP / "pass46f_source_selection.json"
CAND_TAR = REPO / "data/submissions/candidates_pass46f/cg_typed_water_anti_disruption_searchcal_v1.tar.gz"
CAND_RUN = REPO / "data/tournament/benchmark/_cg_cand_extracted/cg_typed_water_anti_disruption_searchcal_v1"


def _ensure_candidate() -> Path:
    if not (CAND_RUN / "main.py").is_file() or not (CAND_RUN / "cg" / "libcg.so").is_file():
        CAND_RUN.mkdir(parents=True, exist_ok=True)
        with tarfile.open(CAND_TAR) as t:
            safe_extract_all(t, CAND_RUN)
    return CAND_RUN


def _parent_frames(source_id: str) -> list[dict]:
    """Every ACTIVE decision frame (n_options>=2, legal action) where the ACTING
    seat is the SOURCE/parent agent. No per-family cap — we want all its choices."""
    frames: list[dict] = []
    for tp in sorted(glob.glob(str(TRACES / "*.json.gz"))):
        try:
            d = json.loads(gzip.open(tp).read())
        except Exception:  # noqa: BLE001
            continue
        a_seat = int(d.get("a_seat", 0))
        # Actual agent ids live in candidate_a/candidate_b (role_a/role_b are
        # semantic labels like "internal_candidate_top_water").
        cand_a, cand_b = d.get("candidate_a"), d.get("candidate_b")
        for i, st in enumerate(d.get("steps") or []):
            if not isinstance(st, list):
                continue
            for seat, o in enumerate(st):
                if not isinstance(o, dict):
                    continue
                if str(o.get("status", "")).upper() != "ACTIVE":
                    continue
                acting = cand_a if seat == a_seat else cand_b
                if acting != source_id:
                    continue
                obs = o.get("observation")
                if not isinstance(obs, dict):
                    continue
                sel, cur = obs.get("select"), obs.get("current")
                if not isinstance(sel, dict) or not isinstance(cur, dict):
                    continue
                opts = sel.get("option") or []
                if len(opts) < 2:
                    continue
                action = o.get("action")
                if not O._is_index_action(action, len(opts), sel.get("minCount"),
                                          sel.get("maxCount")):
                    continue
                chosen0 = action[0] if action else None
                pfam = (TS.family_for_option(opts[chosen0])
                        if isinstance(chosen0, int) and 0 <= chosen0 < len(opts)
                        else "unknown")
                frames.append({
                    "trace": Path(tp).name, "step": i, "seat": seat,
                    "select": sel, "current": cur, "n_options": len(opts),
                    "min_count": sel.get("minCount"), "max_count": sel.get("maxCount"),
                    "parent_selected": list(action), "parent_family": pfam,
                })
    return frames


_SNIPPET = r'''
import importlib.util, json, os, sys
cand_dir, frames_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
os.chdir(cand_dir)
sys.path.insert(0, cand_dir)
spec = importlib.util.spec_from_file_location("cand_ni", os.path.join(cand_dir, "main.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
agent = getattr(m, "agent")
frames = json.loads(open(frames_path).read())
out = []
for fr in frames:
    rec = {}
    try:
        r = agent({"select": fr["select"], "current": fr["current"]})
        rec["decision"] = r if isinstance(r, list) else None
        rec["raised"] = False
    except Exception as e:
        rec["decision"] = None
        rec["raised"] = True
        rec["err"] = type(e).__name__
    out.append(rec)
with open(out_path, "w") as fh:
    json.dump(out, fh)
    fh.flush(); os.fsync(fh.fileno())
print("NI_OK", len(out))
'''


def _run_candidate_on_frames(cand_dir: Path, frames: list[dict]) -> list[dict] | None:
    with tempfile.TemporaryDirectory() as td:
        fp = Path(td) / "frames.json"
        op = Path(td) / "out.json"
        sp = Path(td) / "snip.py"
        fp.write_text(json.dumps([{"select": f["select"], "current": f["current"]}
                                  for f in frames]), encoding="utf-8")
        sp.write_text(_SNIPPET, encoding="utf-8")
        try:
            subprocess.run([sys.executable, str(sp), str(cand_dir), str(fp), str(op)],
                           capture_output=True, text=True, timeout=110)
        except subprocess.TimeoutExpired:
            return None
        if not op.is_file():
            return None
        return json.loads(op.read_text(encoding="utf-8"))


def main() -> int:
    source = json.loads(SOURCE_JSON.read_text(encoding="utf-8"))
    source_id = (source.get("selected_source") or {}).get("candidate_id") \
        or source.get("parent_candidate_id")
    frames = _parent_frames(source_id)
    if not frames:
        raise SystemExit(f"no parent ACTIVE frames found for {source_id}")

    cand_dir = _ensure_candidate()
    decisions = _run_candidate_on_frames(cand_dir, frames)
    if decisions is None or len(decisions) != len(frames):
        raise SystemExit("candidate frame replay failed / incomplete")

    n = len(frames)
    changed = exceptions = illegal = fallback_used = scorer_decisive = 0
    cand_fam_hist: Counter = Counter()
    parent_fam_hist: Counter = Counter()
    first_idx_hist: Counter = Counter()
    per_frame = []
    for fr, dec in zip(frames, decisions):
        opts = fr["select"].get("option") or []
        nopt = len(opts)
        d = dec.get("decision")
        raised = dec.get("raised")
        if raised:
            exceptions += 1
        legal = (isinstance(d, list) and O._is_index_action(
            d, nopt, fr["min_count"], fr["max_count"])) or (d == [] and (
                fr["min_count"] in (0, None)))
        if isinstance(d, list) and not legal:
            illegal += 1
        parent_sel = fr["parent_selected"]
        is_changed = isinstance(d, list) and set(d) != set(parent_sel)
        if is_changed:
            changed += 1
        if isinstance(d, list) and d:
            scorer_decisive += 1
            c0 = d[0]
            if isinstance(c0, int) and 0 <= c0 < nopt:
                cand_fam_hist[TS.family_for_option(opts[c0])] += 1
                first_idx_hist[c0] += 1
        elif isinstance(d, list) and not d:
            fallback_used += 1
        parent_fam_hist[fr["parent_family"]] += 1
        per_frame.append({"trace": fr["trace"], "step": fr["step"],
                          "n_options": nopt, "parent": parent_sel,
                          "candidate": d, "changed": is_changed,
                          "parent_family": fr["parent_family"]})

    changed_rate = round(changed / n, 4)
    # Degeneracy guard: a policy that always picks the same family/index is inert
    # even if "changed" vs parent. Report concentration of the candidate's choices.
    top_fam, top_fam_n = (cand_fam_hist.most_common(1)[0] if cand_fam_hist
                          else (None, 0))
    top_idx_share = round(max(first_idx_hist.values()) / scorer_decisive, 4) \
        if scorer_decisive else None
    distinct_families = len(cand_fam_hist)

    non_inert = changed > 0 and distinct_families >= 2
    safe = exceptions == 0 and illegal == 0

    out = {
        "pass": "46f", "part": "G.1", "kind": "non_inertness_audit",
        "local_only": True, "read_only": True, "no_upload": True,
        "production_mutated": False, "no_game_execution": True,
        "source_parent_id": source_id, "n_parent_frames": n,
        "changed_vs_parent": changed, "changed_rate": changed_rate,
        "agreement_with_parent": round(1 - changed_rate, 4),
        "scorer_decisive": scorer_decisive, "fallback_used": fallback_used,
        "illegal_decisions": illegal, "exceptions": exceptions,
        "candidate_family_histogram": dict(cand_fam_hist.most_common()),
        "parent_family_histogram": dict(parent_fam_hist.most_common()),
        "candidate_top_family": top_fam, "candidate_top_family_n": top_fam_n,
        "candidate_distinct_families": distinct_families,
        "candidate_top_first_index_share": top_idx_share,
        "non_inert": non_inert, "safe": safe,
        "verdict": ("non_inert_and_safe" if (non_inert and safe)
                    else "inert" if not non_inert else "unsafe"),
        "note": ("Non-inertness + legality of an ACTIVE, never-raising policy. NOT a "
                 "strength claim (see Part-H eval). Frames are the parent's recorded "
                 "ACTIVE decisions; hidden state is the real recorded observation."),
        "per_frame_sample": per_frame[:40],
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46f_non_inertness.json").write_text(
        json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")

    fam_rows = "".join(
        f"\n| `{k}` | {v} |" for k, v in out["candidate_family_histogram"].items())
    md = [
        "# Pass 46F (Part G.1) — Decision-trace non-inertness audit vs parent", "",
        "_Deterministic replay of the parent's own ACTIVE decision frames through the "
        "BUILT candidate's `agent()` (no games). Confirms the calibrated policy is "
        "**active** (changes decisions vs the parent), **non-degenerate** (>=2 "
        "distinct action families), **legal**, and **never raises**. This is a "
        "safety/activity property, NOT a strength claim._", "",
        f"- **source/parent:** `{source_id}`",
        f"- **parent ACTIVE frames replayed:** {n}",
        f"- **changed vs parent:** {changed} ({changed_rate:.0%}) · "
        f"agreement {out['agreement_with_parent']:.0%}",
        f"- **scorer decisive / fallback used:** {scorer_decisive} / {fallback_used}",
        f"- **illegal decisions:** {illegal} · **exceptions:** {exceptions}",
        f"- **distinct candidate families:** {distinct_families} · top "
        f"`{top_fam}`×{top_fam_n} · top-first-index share {top_idx_share}",
        f"- **verdict: {out['verdict']}** (non_inert={non_inert}, safe={safe})", "",
        "## Candidate chosen-family histogram", "",
        "| family | n |", "|---|---|", fam_rows.lstrip("\n"), "",
    ]
    (EXP / "pass46f_non_inertness.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"n_frames": n, "changed_rate": changed_rate,
                      "distinct_families": distinct_families,
                      "illegal": illegal, "exceptions": exceptions,
                      "verdict": out["verdict"]}, indent=2))
    return 0 if (non_inert and safe) else 1


if __name__ == "__main__":
    raise SystemExit(main())
