#!/usr/bin/env python3
"""Pass 42 (Part E) — Validation gates for generated candidates.

Runs the full battery of HARD gates over every tarball recorded in the Part D
manifest and records, per candidate, exactly which gates passed/failed and the
admission verdict. Rejected candidates are recorded WITH a reason — never
silently dropped.

Gates (per spec PART E):
  1. tarball-shape validator            6. no public-reference leakage
  2. entrypoint validator               7. duplicate deck / policy detection
  3. deck legality (60 / int / known    8. non-inertness OR meaningful deck-
     IDs / no invented IDs)                composition delta
  4. embedded-deck == deck.csv          9. root-safety re-check (filecmp)
  5. smoke game vs self + vs anchor    10. no upload/submit event emitted

The smoke games hit the native cabt engine, so they run as hard-timeout child
processes; this script is RESUMABLE + wall-budgeted — re-invoke until it prints
``ALL DONE`` (exit 0/1). A tick that still has pending smoke games exits 2.

LOCAL-only. Emits NO events, mutates NO pool, performs NO upload/submit/promote.

Outputs:
    data/experiments/pass42_generated_candidate_validation.json
    data/experiments/pass42_generated_candidate_validation.md
Progress (transient):
    data/experiments/pass42_validation_progress.json
"""

from __future__ import annotations

import filecmp
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.cards.card_db import load_card_db  # noqa: E402
from ptcg_activegraph.decks.deck_io import load_deck  # noqa: E402
from ptcg_activegraph.experiments.runner import run_one_game_subprocess  # noqa: E402
from ptcg_activegraph.tournament import generation as G  # noqa: E402
from ptcg_activegraph.tournament.artifacts import safe_extract_all  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402

EXP = REPO / "data" / "experiments"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
MANIFEST = EXP / "pass42_generated_candidates_manifest.json"
PROGRESS = EXP / "pass42_validation_progress.json"
EXTRACT_DIR = REPO / "data" / "tournament" / "benchmark" / "_gen42_extracted"
REF_MANIFEST = REPO / "data" / "reference_agents" / "reference_agent_manifest.json"
MAIN_EVENTS = REPO / "data" / "tournament" / "events.jsonl"
BENCH_EVENTS = REPO / "data" / "tournament" / "benchmark" / "benchmark_events.jsonl"

NEVER_EMIT_EVENT_TYPES = {"SubmissionUploaded", "KaggleScoreUpdated",
                          "CandidatePromoted", "SubmissionQueued"}
GAME_TIMEOUT = 90
WALL_BUDGET = 60


def _ref_ids() -> set[str]:
    if not REF_MANIFEST.is_file():
        return set()
    raw = json.loads(REF_MANIFEST.read_text(encoding="utf-8"))
    return {a.get("agent_id") for a in raw.get("agents", [])}


def _extract(tarball: Path, dest: Path) -> Path:
    if not (dest / "main.py").is_file():
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tarball) as t:
            safe_extract_all(t, dest)
    return dest


def _run_validator(script: str, tarball: Path) -> dict:
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / script),
                           str(tarball)],
                          capture_output=True, text=True, cwd=str(REPO),
                          timeout=120)
    tail = (proc.stdout.strip().splitlines() or [proc.stderr.strip()])[-1:]
    return {"rc": proc.returncode, "ok": proc.returncode == 0,
            "tail": tail[0] if tail else ""}


def _scan_forbidden_events() -> dict:
    forbidden = 0
    forbidden_on_generated = 0
    for path in (MAIN_EVENTS, BENCH_EVENTS):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            et = e.get("event_type") or e.get("type")
            if et in NEVER_EMIT_EVENT_TYPES:
                forbidden += 1
                blob = json.dumps(e)
                if "generated_" in blob:
                    forbidden_on_generated += 1
    return {"forbidden_total": forbidden,
            "forbidden_referencing_generated": forbidden_on_generated,
            "ok": forbidden == 0 and forbidden_on_generated == 0}


def _static_gates(cand: dict, sources: dict, card_db, ref_ids: set[str],
                  forbidden: dict) -> dict:
    """All non-game gates. Pure / fast; computed once and cached."""
    gid = cand["generated_candidate_id"]
    tarball = REPO / cand["generated_tarball_path"]
    src = sources.get(cand["source_candidate_id"])

    tar_dest = _extract(tarball, EXTRACT_DIR / gid)
    deck_path = tar_dest / "deck.csv"
    main_src = (tar_dest / "main.py").read_text(encoding="utf-8")
    deck_ids = [int(x) for x in deck_path.read_text(encoding="utf-8").split()
                if x.strip()]
    deck_ms = sorted(deck_ids)

    g = {}
    g["tarball_shape"] = _run_validator("validate_candidate_tarball.py", tarball)
    g["entrypoint"] = _run_validator("validate_candidate_entrypoint.py", tarball)

    deck_60_int = len(deck_ids) == 60 and all(isinstance(x, int) for x in deck_ids)
    known = src is not None and all(card_db.get(c) is not None for c in deck_ids)
    no_invented = src is not None and set(deck_ids).issubset(set(src.deck_ids))
    g["deck_legality"] = {
        "ok": bool(deck_60_int and known and no_invented),
        "deck_60_int": deck_60_int, "known_ids": known,
        "no_invented_ids": no_invented}

    embedded = sorted(G.extract_embedded_deck(main_src))
    g["embedded_eq_deckcsv"] = {"ok": embedded == deck_ms,
                                "embedded_len": len(embedded)}

    is_stdlib = G.is_stdlib_lane_tarball(tarball)
    parent = cand.get("parent_candidate_id")
    leak_ok = (is_stdlib and parent in sources and parent not in ref_ids
               and gid not in ref_ids)
    g["no_public_ref_leakage"] = {
        "ok": bool(leak_ok), "stdlib_lane": is_stdlib,
        "parent_is_internal_source": parent in sources,
        "parent_not_reference": parent not in ref_ids}

    dup_against = sorted(s.candidate_id for s in sources.values()
                         if sorted(s.deck_ids) == deck_ms)
    duplicate = len(dup_against) > 0
    g["duplicate_detection"] = {"ok": not duplicate, "duplicate_of": dup_against}

    has_deck_delta = bool(cand.get("deck_delta")
                          and (cand["deck_delta"].get("removed")
                               or cand["deck_delta"].get("added")))
    deck_changed = src is not None and deck_ms != sorted(src.deck_ids)
    meaningful_delta = bool(has_deck_delta and deck_changed)
    # v0 does NOT prove live policy non-inertness (deferred to v1); a policy-only
    # candidate therefore has no admissible non-inertness signal here.
    g["non_inert_or_delta"] = {
        "ok": meaningful_delta,
        "meaningful_deck_delta": meaningful_delta,
        "live_non_inertness_proven": False,
        "policy_delta_present": cand.get("policy_delta") is not None}

    g["root_safety"] = {
        "ok": all(filecmp.cmp(REPO / fn, BASELINE / fn, shallow=False)
                  for fn in ("main.py", "deck.csv"))}
    g["no_upload_submit_event"] = {"ok": forbidden["ok"], **forbidden}

    g["_deck_ids"] = deck_ids
    return g


def _static_hard_ok(g: dict) -> bool:
    return all([
        g["tarball_shape"]["ok"], g["entrypoint"]["ok"],
        g["deck_legality"]["ok"], g["embedded_eq_deckcsv"]["ok"],
        g["no_public_ref_leakage"]["ok"], g["duplicate_detection"]["ok"],
        g["non_inert_or_delta"]["ok"], g["root_safety"]["ok"],
        g["no_upload_submit_event"]["ok"]])


def _anchor_for(cand: dict, anchors: list[str]) -> str | None:
    parent = cand.get("parent_candidate_id")
    for a in anchors:
        if a != parent:
            return a
    return anchors[0] if anchors else None


def _load_progress() -> dict:
    if PROGRESS.is_file():
        try:
            return json.loads(PROGRESS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"static": {}, "smoke": {}, "anchor_choice": {}}


def _save_progress(p: dict) -> None:
    PROGRESS.write_text(json.dumps(p, indent=2, default=str), encoding="utf-8")


def _smoke_game(cand_dir: Path, opp_dir: Path) -> dict:
    res = run_one_game_subprocess(
        control_main=opp_dir / "main.py", control_deck=load_deck(opp_dir / "deck.csv"),
        cand_main=cand_dir / "main.py", cand_deck=load_deck(cand_dir / "deck.csv"),
        candidate_seat=0, timeout_seconds=GAME_TIMEOUT)
    return {"completed": bool(res.get("completed")), "timeout": bool(res.get("timeout")),
            "error": res.get("error"), "steps": res.get("steps")}


def _finalize(prog: dict, manifest: dict) -> int:
    cands = manifest["candidates"]
    results = []
    admitted_ids = []
    consistency_ok = True

    for cand in cands:
        gid = cand["generated_candidate_id"]
        g = prog["static"][gid]
        self_key, anchor_key = f"{gid}::self", f"{gid}::anchor"
        smoke_self = prog["smoke"].get(self_key)
        smoke_anchor = prog["smoke"].get(anchor_key)
        smoke_self_ok = bool(smoke_self and smoke_self["completed"]
                             and not smoke_self["error"])
        smoke_anchor_ok = bool(smoke_anchor and smoke_anchor["completed"]
                               and not smoke_anchor["error"])

        admit = bool(_static_hard_ok(g) and smoke_self_ok and smoke_anchor_ok)
        if admit:
            admitted_ids.append(gid)

        # Reasons for rejection (never silent).
        reasons = []
        if not g["tarball_shape"]["ok"]:
            reasons.append("tarball-shape gate failed")
        if not g["entrypoint"]["ok"]:
            reasons.append("entrypoint gate failed")
        if not g["deck_legality"]["ok"]:
            reasons.append(f"deck legality failed ({g['deck_legality']})")
        if not g["embedded_eq_deckcsv"]["ok"]:
            reasons.append("embedded-deck != deck.csv")
        if not g["no_public_ref_leakage"]["ok"]:
            reasons.append("public-reference leakage")
        if not g["duplicate_detection"]["ok"]:
            reasons.append(f"duplicate deck of {g['duplicate_detection']['duplicate_of']}")
        if not g["non_inert_or_delta"]["ok"]:
            if g["non_inert_or_delta"]["policy_delta_present"]:
                reasons.append("policy-only candidate; live non-inertness not "
                               "proven in v0 (deferred to v1)")
            else:
                reasons.append("inert: no meaningful deck-composition delta")
        if not g["root_safety"]["ok"]:
            reasons.append("root main.py/deck.csv changed")
        if not g["no_upload_submit_event"]["ok"]:
            reasons.append("forbidden upload/submit event present")
        if _static_hard_ok(g) and not (smoke_self_ok and smoke_anchor_ok):
            reasons.append("smoke game did not complete")

        # Consistency: gate verdict must match the manifest's admit INTENT.
        if bool(cand.get("admit")) != admit:
            consistency_ok = False

        results.append({
            "generated_candidate_id": gid,
            "family_id": cand["family_id"],
            "operator": cand["operator"],
            "source_candidate_id": cand["source_candidate_id"],
            "intended_admit": bool(cand.get("admit")),
            "admitted": admit,
            "rejection_reasons": reasons,
            "gates": {k: (v["ok"] if isinstance(v, dict) else v)
                      for k, v in g.items() if not k.startswith("_")},
            "smoke_vs_self": {"ran": smoke_self is not None, "ok": smoke_self_ok,
                              "detail": smoke_self},
            "smoke_vs_anchor": {"anchor": prog["anchor_choice"].get(gid),
                                "ran": smoke_anchor is not None,
                                "ok": smoke_anchor_ok, "detail": smoke_anchor},
        })

    decision = ("candidate_generation_v0_enabled" if admitted_ids
                else "generation_infrastructure_ready_no_admissions")
    out = {
        "pass_id": manifest["pass_id"], "seed": manifest["seed"],
        "n_candidates": len(cands), "n_admitted": len(admitted_ids),
        "admitted_ids": admitted_ids,
        "gate_manifest_consistency_ok": consistency_ok,
        "decision": decision,
        "results": results,
        "guardrails": {"no_upload": True, "no_submit": True, "no_promotion": True,
                       "no_events_emitted_by_validation": True},
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass42_generated_candidate_validation.json").write_text(
        json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8")
    (EXP / "pass42_generated_candidate_validation.md").write_text(
        _md(out), encoding="utf-8")

    print(f"ALL DONE: admitted={len(admitted_ids)}/{len(cands)} "
          f"decision={decision} consistency_ok={consistency_ok} "
          f"admitted_ids={admitted_ids}")
    return 0 if consistency_ok else 1


def _md(out: dict) -> str:
    L = ["# Pass 42 (Part E) — Generated Candidate Validation", ""]
    L.append("_LOCAL-only hard gates. Admission means *eligible to be evaluated as "
             "probation*, NOT *good*. No upload/submit/promotion; validation emits "
             "no events._")
    L.append("")
    L.append(f"- candidates validated: **{out['n_candidates']}** | "
             f"admitted (probation-eligible): **{out['n_admitted']}**")
    L.append(f"- admitted ids: {out['admitted_ids'] or 'none'}")
    L.append(f"- gate/manifest-intent consistency: **{out['gate_manifest_consistency_ok']}**")
    L.append(f"- **decision: {out['decision']}**")
    L.append("")
    L.append("| candidate | admitted | tarball | entry | deck | embed | no-leak | "
             "uniq | delta | smoke self | smoke anchor |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in out["results"]:
        g = r["gates"]
        def yn(b):
            return "Y" if b else "·"
        L.append(f"| `{r['generated_candidate_id']}` | "
                 f"{'**YES**' if r['admitted'] else 'no'} | "
                 f"{yn(g['tarball_shape'])} | {yn(g['entrypoint'])} | "
                 f"{yn(g['deck_legality'])} | {yn(g['embedded_eq_deckcsv'])} | "
                 f"{yn(g['no_public_ref_leakage'])} | {yn(g['duplicate_detection'])} | "
                 f"{yn(g['non_inert_or_delta'])} | {yn(r['smoke_vs_self']['ok'])} | "
                 f"{yn(r['smoke_vs_anchor']['ok'])} |")
    L.append("")
    L.append("## Per-candidate detail")
    for r in out["results"]:
        L.append("")
        L.append(f"### `{r['generated_candidate_id']}` — "
                 f"{'ADMITTED (probation-eligible)' if r['admitted'] else 'REJECTED'}")
        L.append(f"- operator `{r['operator']}` from source "
                 f"`{r['source_candidate_id']}` (intended_admit={r['intended_admit']})")
        if r["smoke_vs_self"]["detail"]:
            L.append(f"- smoke vs self: {r['smoke_vs_self']['detail']}")
        if r["smoke_vs_anchor"]["detail"]:
            L.append(f"- smoke vs anchor `{r['smoke_vs_anchor']['anchor']}`: "
                     f"{r['smoke_vs_anchor']['detail']}")
        if r["rejection_reasons"]:
            L.append(f"- rejection reasons: {r['rejection_reasons']}")
        else:
            L.append("- all hard gates passed.")
    L.append("")
    return "\n".join(L)


def main() -> int:
    if not MANIFEST.is_file():
        print(f"FAIL: manifest missing ({MANIFEST}); run the builder first.")
        return 1
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    card_db = load_card_db()
    pool = CandidatePool.load()
    sources = {s.candidate_id: s for s in G.eligible_sources(pool)}
    anchors = sorted(s.candidate_id for s in sources.values()
                     if s.status == "portfolio_anchor")
    ref_ids = _ref_ids()
    forbidden = _scan_forbidden_events()

    prog = _load_progress()

    # --- static gates (compute once, cache) -------------------------------
    for cand in manifest["candidates"]:
        gid = cand["generated_candidate_id"]
        if gid not in prog["static"]:
            prog["static"][gid] = _static_gates(cand, sources, card_db, ref_ids,
                                                 forbidden)
            prog["anchor_choice"][gid] = _anchor_for(cand, anchors)
            _save_progress(prog)

    # --- smoke games (only for static-passing, admit-intended candidates) --
    pending: list[tuple[str, str]] = []
    for cand in manifest["candidates"]:
        gid = cand["generated_candidate_id"]
        if not (_static_hard_ok(prog["static"][gid]) and cand.get("admit")):
            continue
        for kind in ("self", "anchor"):
            if f"{gid}::{kind}" not in prog["smoke"]:
                pending.append((gid, kind))

    start = time.time()
    ran = 0
    for gid, kind in pending:
        if time.time() - start > WALL_BUDGET and ran > 0:
            break
        cand_dir = EXTRACT_DIR / gid
        if kind == "self":
            opp_dir = cand_dir
        else:
            anchor_id = prog["anchor_choice"][gid]
            anchor_tar = G.resolve_tarball(sources[anchor_id].tarball_path)
            opp_dir = _extract(anchor_tar, EXTRACT_DIR / f"_anchor_{anchor_id}")
        t0 = time.time()
        res = _smoke_game(cand_dir, opp_dir)
        res["seconds"] = round(time.time() - t0, 1)
        prog["smoke"][f"{gid}::{kind}"] = res
        _save_progress(prog)
        ran += 1
        flag = "OK" if (res["completed"] and not res["error"]) else "FAIL"
        print(f"[{flag}] {gid}::{kind} {res['seconds']}s steps={res.get('steps')} "
              f"err={res.get('error')}")

    remaining = [(gid, k) for (gid, k) in pending
                 if f"{gid}::{k}" not in prog["smoke"]]
    if remaining:
        print(f"TICK DONE: ran {ran}, {len(remaining)} smoke games remaining — re-invoke")
        return 2
    return _finalize(prog, manifest)


if __name__ == "__main__":
    raise SystemExit(main())
