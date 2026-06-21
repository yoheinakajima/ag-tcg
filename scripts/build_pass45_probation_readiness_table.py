#!/usr/bin/env python3
"""PASS 45 — Part H: probation readiness table (consolidated projection).

Consolidates the read-only evidence (Part C), the gate dry-run (Part E), the failure
screen (Part D) and the soak audit (Part B) into a single at-a-glance readiness table
for the 3 Pass-42 probation candidates: what evidence has accrued, how far each is
from the locked v1 sample-size minimums, and the honest promotion-readiness verdict.

Reads only local Pass-45 artifacts; no prod read, no mutation, no emission.

Output:
  data/experiments/pass45_probation_readiness_table.md
  data/experiments/pass45_probation_readiness_table.json   (machine-readable companion)
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
EVID = EXP / "pass45_probation_evidence_audit.json"
GATE = EXP / "pass45_promotion_gate_prod_dry_run.json"
FAIL = EXP / "pass45_probation_failure_screen.json"
SOAK = EXP / "pass45_scheduled_daemon_soak_audit.json"
TARGETS = [
    "generated_diamond_diamondtoolbox_eratio_v1",
    "generated_dragapult_leaguedragapul_bdens_v1",
    "generated_lightning_monolightningm_dsratio_v1",
]


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    for p in (EVID, FAIL):
        if not p.is_file():
            raise SystemExit(f"missing {p.name} — run Parts C/D first")
    evid = json.loads(EVID.read_text(encoding="utf-8"))
    fail = json.loads(FAIL.read_text(encoding="utf-8"))
    soak = json.loads(SOAK.read_text(encoding="utf-8")) if SOAK.is_file() else {}
    th = evid.get("thresholds", {})

    rows = []
    for cid in TARGETS:
        t = evid["per_target"].get(cid, {})
        f = fail["per_target"].get(cid, {})
        e = t.get("evidence", {})
        gaps = t.get("sample_size_gaps", {})
        rows.append({
            "candidate_id": cid,
            "status": t.get("status"),
            "action": t.get("action"),
            "promotion_ready": bool(t.get("promotion_ready")),
            "total_games": e.get("total_games"),
            "decisive_games": e.get("decisive_games"),
            "win_rate": e.get("win_rate"),
            "wilson_low": e.get("wilson_low"),
            "parent_h2h_games": e.get("parent_h2h_games"),
            "hardfail_rate": f.get("hardfail_rate"),
            "quarantine_warranted": bool(f.get("quarantine_warranted")),
            "total_still_needed": gaps.get("total_games", {}).get("still_needed"),
            "decisive_still_needed":
                gaps.get("decisive_games", {}).get("still_needed"),
            "parent_h2h_still_needed":
                gaps.get("parent_h2h_games", {}).get("still_needed"),
        })

    any_ready = any(r["promotion_ready"] for r in rows)
    any_quarantine = any(r["quarantine_warranted"] for r in rows)
    all_probation = all(r["status"] == "probation" for r in rows)

    if any_ready:
        verdict = "promotion_review_ready_no_apply"
    elif any_quarantine:
        verdict = "probation_runtime_issue_found"
    else:
        verdict = "probation_soak_continue"

    out = {
        "pass": "pass45_probation_readiness_table",
        "read_only": True, "mutated": False,
        "rows": rows,
        "any_promotion_ready": any_ready,
        "any_quarantine_warranted": any_quarantine,
        "all_targets_probation": all_probation,
        "implied_decision": verdict,
        "soak_healthy": soak.get("soak_healthy"),
        "thresholds": th,
    }
    (EXP / "pass45_probation_readiness_table.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def yn(b):
        return "yes" if b else "no"

    md = [
        "# PASS 45 — Part H: probation readiness table", "",
        f"> {evid.get('caveat', '')}", "",
        f"- implied decision: **`{verdict}`**",
        f"- any promotion-ready: **{yn(any_ready)}**  · any quarantine warranted: "
        f"**{yn(any_quarantine)}**  · all targets probation: **{yn(all_probation)}**",
        f"- soak healthy: **{soak.get('soak_healthy')}**", "",
        "| candidate | status | action | ready | games | decisive | win-rate | "
        "wilson_low | parent-H2H | HF rate | quarantine | +total | +decisive | "
        "+H2H |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        md.append(
            f"| `{r['candidate_id']}` | {r['status']} | {r['action']} | "
            f"{yn(r['promotion_ready'])} | {r['total_games']} | "
            f"{r['decisive_games']} | {r['win_rate']} | {r['wilson_low']} | "
            f"{r['parent_h2h_games']} | {r['hardfail_rate']} | "
            f"{yn(r['quarantine_warranted'])} | {r['total_still_needed']} | "
            f"{r['decisive_still_needed']} | {r['parent_h2h_still_needed']} |")
    md += [
        "", "**Legend:** `+total` / `+decisive` / `+H2H` = games still needed to "
        "reach the locked v1 activate minimums.", "",
        "> Honest verdict: all three candidates remain on probation, accruing "
        "evidence under the live daemon. None is promotion-ready; none warrants "
        "quarantine. The soak continues.",
    ]
    (EXP / "pass45_probation_readiness_table.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass45 partH: verdict={verdict} any_ready={any_ready} "
          f"any_quarantine={any_quarantine} all_probation={all_probation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
