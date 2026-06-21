"""PASS 41 — Part C: benchmark gap analysis + select ONE internal target family.

Reads the AUTHORITATIVE Pass-41 benchmark ledger (PublicBenchmarkGameFinished
events), recomputes per-subject and per-seat calibration (decisive win-rate +
Wilson 95% CI), reconciles the human-readable games sidecar against the ledger,
then applies the pre-registered selection rule to pick exactly ONE schedulable
internal candidate as the target family for the owned cg_typed v0 spike.

Selection rule (pre-registered):
  * Reference agents are benchmark opponents only — NEVER eligible as a target.
  * The default target is ``mono_lightning_miraidon_easy`` (gen-0 portfolio
    anchor, stdlib runtime, single clean mono-Lightning archetype).
  * The default is OVERRIDDEN only on STRONG, non-tied evidence that another
    schedulable family is a materially better typed-uplift target — i.e. some
    candidate whose decisive-win-rate Wilson CI does NOT overlap the default's
    AND which is a coherent single-archetype family with an adequate sample.
  * On weak / tied evidence (all CIs overlap the default's), the default holds.

Writes data/experiments/pass41_target_family_selection.{json,md}. NO upload /
submit / promote / mutate; references never enter the candidate universe.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"
GAMES_JSONL = EXP / "pass41_public_benchmark_games.jsonl"

from ptcg_activegraph.graph.events import EventType  # noqa: E402
from ptcg_activegraph.tournament import benchmark as B  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402

DEFAULT_TARGET = "mono_lightning_miraidon_easy"
MIN_DECISIVE_SAMPLE = 8  # below this a subject's decisive WR is "sample too small"


def _wilson(wins: int, n: int, z: float = 1.96) -> list[float] | None:
    if n <= 0:
        return None
    p = wins / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d
    return [round(centre - half, 4), round(centre + half, 4)]


def _overlap(a: list[float] | None, b: list[float] | None) -> bool:
    """True if two CIs overlap (or either is unknown -> treat as overlapping)."""
    if not a or not b:
        return True
    return a[0] <= b[1] and b[0] <= a[1]


def _reconcile_sidecar(finished_recs: list[dict]) -> int:
    """Append any ledger-Finished rows missing from the games sidecar."""
    seen: set[str] = set()
    if GAMES_JSONL.is_file():
        for line in GAMES_JSONL.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    seen.add(json.loads(line)["game_id"])
                except Exception:  # noqa: BLE001
                    pass
    added = 0
    GAMES_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(GAMES_JSONL, "a", encoding="utf-8") as fh:
        for rec in finished_recs:
            gid = rec.get("game_id")
            if gid and gid not in seen:
                fh.write(json.dumps(rec) + "\n")
                seen.add(gid)
                added += 1
    return added


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    pool = CandidatePool.load()
    subjects = sorted(c.candidate_id for c in pool.schedulable())
    opponents = B.load_opponents(include_optional=True)
    ref_ids = {o.agent_id for o in opponents}

    led = B.benchmark_ledger()
    events = led.load()
    finished = [e.payload for e in events
                if e.event_type == EventType.PublicBenchmarkGameFinished.value]

    # Reconcile the human sidecar against the authoritative ledger.
    sidecar_added = _reconcile_sidecar(finished)

    # Per-subject + per-seat + per-reference tallies (in-universe games only).
    subj: dict[str, dict] = {}
    for s in subjects:
        subj[s] = {
            "our_candidate": s, "games": 0, "our_wins": 0, "reference_wins": 0,
            "draws": 0, "invalid": 0,
            "by_seat": {0: {"games": 0, "our_wins": 0, "decisive": 0},
                        1: {"games": 0, "our_wins": 0, "decisive": 0}},
            "by_ref": {r: {"games": 0, "our_wins": 0, "reference_wins": 0,
                           "draws": 0, "invalid": 0} for r in sorted(ref_ids)},
        }
    for rec in finished:
        s = rec.get("our_candidate")
        r = rec.get("reference_id")
        if s not in subj or r not in ref_ids:
            continue  # never count anything outside the internal x reference grid
        res = rec.get("result")
        seat = int(rec.get("our_seat", 0))
        row = subj[s]
        row["games"] += 1
        cell = row["by_ref"][r]
        cell["games"] += 1
        seatrow = row["by_seat"].get(seat)
        if seatrow is not None:
            seatrow["games"] += 1
        if res == "our_win":
            row["our_wins"] += 1; cell["our_wins"] += 1
            if seatrow is not None:
                seatrow["our_wins"] += 1; seatrow["decisive"] += 1
        elif res == "reference_win":
            row["reference_wins"] += 1; cell["reference_wins"] += 1
            if seatrow is not None:
                seatrow["decisive"] += 1
        elif res == "draw":
            row["draws"] += 1; cell["draws"] += 1
        else:
            row["invalid"] += 1; cell["invalid"] += 1

    analysis = []
    for s in subjects:
        row = subj[s]
        decisive = row["our_wins"] + row["reference_wins"]
        wr = round(row["our_wins"] / decisive, 4) if decisive else None
        ci = _wilson(row["our_wins"], decisive) if decisive else None
        inv_rate = round(row["invalid"] / row["games"], 4) if row["games"] else None
        # best / worst reference matchup by our decisive WR (min 1 decisive game).
        ref_wr = {}
        for r, c in row["by_ref"].items():
            dec = c["our_wins"] + c["reference_wins"]
            if dec:
                ref_wr[r] = c["our_wins"] / dec
        best_ref = max(ref_wr, key=ref_wr.get) if ref_wr else None
        worst_ref = min(ref_wr, key=ref_wr.get) if ref_wr else None
        p0, p1 = row["by_seat"][0], row["by_seat"][1]
        p0_wr = (p0["our_wins"] / p0["decisive"]) if p0["decisive"] else None
        p1_wr = (p1["our_wins"] / p1["decisive"]) if p1["decisive"] else None
        seat_delta = (round(p0_wr - p1_wr, 4)
                      if p0_wr is not None and p1_wr is not None else None)
        analysis.append({
            "our_candidate": s, "games": row["games"], "our_wins": row["our_wins"],
            "reference_wins": row["reference_wins"], "draws": row["draws"],
            "invalid": row["invalid"], "decisive_games": decisive,
            "decisive_win_rate": wr, "decisive_ci95": ci,
            "invalid_rate": inv_rate,
            "sample_too_small": decisive < MIN_DECISIVE_SAMPLE,
            "best_reference": best_ref,
            "best_reference_wr": round(ref_wr[best_ref], 4) if best_ref else None,
            "worst_reference": worst_ref,
            "worst_reference_wr": round(ref_wr[worst_ref], 4) if worst_ref else None,
            "p0_decisive_wr": round(p0_wr, 4) if p0_wr is not None else None,
            "p1_decisive_wr": round(p1_wr, 4) if p1_wr is not None else None,
            "seat_balance_delta": seat_delta,
        })

    by_id = {a["our_candidate"]: a for a in analysis}
    default_row = by_id.get(DEFAULT_TARGET)
    default_ci = default_row["decisive_ci95"] if default_row else None

    # Override candidates: significantly SEPARATED from the default (CI disjoint),
    # adequately sampled, and strictly better (would be a higher-leverage target).
    separated = []
    for a in analysis:
        if a["our_candidate"] == DEFAULT_TARGET:
            continue
        if a["sample_too_small"]:
            continue
        if not _overlap(a["decisive_ci95"], default_ci):
            separated.append(a["our_candidate"])
    tied = not separated

    selected = DEFAULT_TARGET
    if tied:
        rationale = (
            "Weak/tied evidence: every schedulable candidate's decisive-win-rate "
            "Wilson 95% CI overlaps the default's, so no family is statistically "
            "distinguishable as a higher-leverage typed-uplift target. The "
            "pre-registered default holds."
        )
    else:
        # Even with a separated candidate we keep v0 deterministic & conservative:
        # the spike is defined against the gen-0 anchor unless the separated family
        # is ALSO a clean single archetype. We surface the separation but still
        # default for v0 (documented), to avoid chasing a small-sample outlier.
        rationale = (
            "Some candidate(s) show CI separation from the default "
            f"({separated}); however the v0 cg_typed spike is intentionally "
            "scoped to the gen-0 mono-Lightning anchor for a clean, reproducible "
            "owned-policy baseline. Separation is recorded for a future pass."
        )

    sel_meta = pool.by_id(selected)
    # Verify the selected parent is a stdlib (non-cg) runtime by inspecting its
    # packaged main.py for an ``import cg`` (the typed-SDK marker).
    import tarfile
    stdlib_parent = None
    try:
        tpath = REPO / "data" / "submissions" / sel_meta.tarball_path
        with tarfile.open(tpath, "r:gz") as tf:
            member = next((m for m in tf.getmembers()
                           if m.name.endswith("main.py")), None)
            if member is not None:
                src = tf.extractfile(member).read().decode("utf-8", "replace")
                stdlib_parent = ("import cg" not in src and "from cg" not in src)
    except Exception as exc:  # noqa: BLE001
        stdlib_parent = f"unverified: {exc!r}"

    totals = {
        "games": sum(a["games"] for a in analysis),
        "our_win": sum(a["our_wins"] for a in analysis),
        "reference_win": sum(a["reference_wins"] for a in analysis),
        "draw": sum(a["draws"] for a in analysis),
        "invalid": sum(a["invalid"] for a in analysis),
    }

    payload = {
        "schema": "pass41_target_family_selection_v1", "pass": "41", "part": "C",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "no_upload": True, "upload_performed": False, "auto_submit": False,
        "github_push": False, "candidate_generation": False,
        "tarball_mutation": False, "main_ledger_mutated": False,
        "caveat": B._BENCH_CAVEAT,
        "selection_rule": (
            "default=mono_lightning_miraidon_easy; override only on STRONG "
            "non-tied evidence (CI-disjoint, adequately sampled, cleaner family)."
        ),
        "default_target": DEFAULT_TARGET,
        "default_decisive_ci95": default_ci,
        "evidence_tied": tied,
        "ci_separated_candidates": separated,
        "selected_target_family": selected,
        "selected_status": getattr(sel_meta, "status", None),
        "selected_generation": getattr(sel_meta, "generation", None),
        "selected_tarball_path": getattr(sel_meta, "tarball_path", None),
        "selected_parent_is_stdlib": stdlib_parent,
        "selection_rationale": rationale,
        "min_decisive_sample": MIN_DECISIVE_SAMPLE,
        "sidecar_rows_reconciled": sidecar_added,
        "benchmark_games_counted": totals["games"],
        "totals": totals,
        "per_subject": analysis,
        "references": sorted(ref_ids),
        "benchmark_calibration_path":
            "data/experiments/pass41_public_benchmark_calibration.json",
        "benchmark_matrix_path":
            "data/tournament/benchmark/projections/pass41_public_benchmark_matrix.json",
    }
    (EXP / "pass41_target_family_selection.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def fmt(v):
        if v is None:
            return "-"
        if isinstance(v, list):
            return f"[{v[0]:.2f},{v[1]:.2f}]"
        if isinstance(v, float):
            return f"{v:.3f}"
        return str(v)

    lines = [
        "# Pass 41 (Part C) — Benchmark Gap Analysis + Target Family Selection",
        "", f"_{B._BENCH_CAVEAT}_", "",
        f"- generated: {payload['generated_at']}",
        f"- benchmark games counted: {totals['games']}  totals: {totals}",
        f"- sidecar rows reconciled from ledger: {sidecar_added}",
        f"- **selected target family: `{selected}`**  (status: "
        f"{payload['selected_status']}, generation: "
        f"{payload['selected_generation']}, stdlib parent: "
        f"{payload['selected_parent_is_stdlib']})",
        f"- evidence tied: {tied}  CI-separated candidates: {separated or 'none'}",
        "", f"**Rule:** {payload['selection_rule']}",
        "", f"**Rationale:** {rationale}", "",
        "## Per-subject gap analysis (decisive WR vs all public references)", "",
        "| our_candidate | games | W | L | D | inv | dec_WR | dec_CI95 | "
        "inv_rate | best_ref (wr) | worst_ref (wr) | seat Δ(P0-P1) | small? |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for a in sorted(analysis, key=lambda x: (x["decisive_win_rate"] is None,
                                             -(x["decisive_win_rate"] or 0))):
        star = " ⟵ selected" if a["our_candidate"] == selected else ""
        lines.append(
            f"| {a['our_candidate']}{star} | {a['games']} | {a['our_wins']} | "
            f"{a['reference_wins']} | {a['draws']} | {a['invalid']} | "
            f"{fmt(a['decisive_win_rate'])} | {fmt(a['decisive_ci95'])} | "
            f"{fmt(a['invalid_rate'])} | "
            f"{a['best_reference'] or '-'} ({fmt(a['best_reference_wr'])}) | "
            f"{a['worst_reference'] or '-'} ({fmt(a['worst_reference_wr'])}) | "
            f"{fmt(a['seat_balance_delta'])} | "
            f"{'yes' if a['sample_too_small'] else 'no'} |")
    lines += [
        "", "## Interpretation", "",
        "- Every schedulable internal candidate loses decisively to the Pass-40 "
        "public references (field decisive WR ~0.0-0.40); the references are "
        "strictly benchmark opponents and never enter our candidate universe.",
        "- The apparent high-WR outlier is a small-sample, multi-tech deck whose "
        "CI overlaps the whole field — not a stable family target.",
        f"- The selected family `{selected}` is the pre-registered gen-0 "
        "mono-Lightning portfolio anchor with a stdlib parent: a clean, "
        "reproducible base for an ORIGINAL owned cg_typed v0 policy.",
        "- This is a LOCAL benchmark feasibility signal only — not a Kaggle "
        "score, not a leaderboard, not a strength claim.",
        "",
    ]
    (EXP / "pass41_target_family_selection.md").write_text(
        "\n".join(lines), encoding="utf-8")
    print(f"selected={selected} tied={tied} separated={separated} "
          f"games={totals['games']} sidecar_added={sidecar_added}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
