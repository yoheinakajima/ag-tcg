#!/usr/bin/env python3
"""Pass 42 (Part D) — Candidate Generation v0 BUILDER.

Materializes the deterministic admission plan into byte-deterministic tarballs
under ``data/submissions/generated_pass42/`` and writes a full lineage manifest.

What this builder DOES:
  * builds <=3 admitted deck-composition candidates (one per family, distinct
    operators) from eligible internal sources;
  * builds the two NON-admitted regression examples
    (``conservative_policy_weight_delta`` + ``noop_sentinel``) so the validation
    gates (Part E) can prove they are rejected.

What this builder NEVER does (HARD guardrails):
  * NO Kaggle upload/submit, NO GitHub push;
  * NO root ``main.py`` / ``deck.csv`` mutation (re-checked here, filecmp-derived);
  * NO tarball deletion, and NO overwrite of a differing tarball (idempotent by
    sha256 — re-running rebuilds byte-identical tarballs);
  * NO promotion / queue / pool mutation (admission is Part F).

Outputs:
    data/submissions/generated_pass42/<generated_id>.tar.gz
    data/experiments/pass42_generated_candidates_manifest.json
    data/experiments/pass42_generated_candidates_manifest.md
"""

from __future__ import annotations

import filecmp
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.cards.card_db import load_card_db  # noqa: E402
from ptcg_activegraph.tournament import generation as G  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402

EXP = REPO / "data" / "experiments"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"


def _root_safety() -> dict:
    """Honest, filecmp-derived check that root main.py/deck.csv are untouched."""
    checks = {}
    for fn in ("main.py", "deck.csv"):
        root = REPO / fn
        base = BASELINE / fn
        if root.is_file() and base.is_file():
            checks[fn] = {
                "exists": True,
                "identical_to_baseline": filecmp.cmp(root, base, shallow=False),
                "sha256": G.sha256_file(root),
            }
        else:
            checks[fn] = {"exists": root.is_file(),
                          "identical_to_baseline": None, "sha256": None}
    checks["all_identical"] = all(
        checks[fn]["identical_to_baseline"] is True for fn in ("main.py", "deck.csv"))
    return checks


def _build_one(src: G.Source, source_gen: int, operator: str,
               new_deck_ids, deck_delta: dict, policy_delta: dict | None,
               reason: str, params: dict, gid: str, admit: bool) -> dict:
    """Render artifact bytes, build a deterministic tarball, write idempotently,
    and return the manifest entry. Deck operators rewrite BOTH deck.csv and the
    embedded fallback; the policy operator leaves the deck multiset unchanged."""
    if policy_delta is not None and new_deck_ids is None:
        # Deck UNCHANGED: keep the source deck multiset; only the policy weight
        # changes in main.py.
        deck_ids = list(src.deck_ids)
        new_main = G.rewrite_policy_weight(
            src.main_src, policy_delta["which"], policy_delta["key"],
            policy_delta["new"])
    else:
        deck_ids = list(new_deck_ids)
        new_main = G.rewrite_embedded_deck(src.main_src, deck_ids)

    new_deck_csv = G.render_deck_csv(deck_ids)
    main_b = new_main.encode("utf-8")
    deck_b = new_deck_csv.encode("utf-8")

    # Internal-consistency self-assert (the Part E gates re-prove this honestly):
    embedded = sorted(G.extract_embedded_deck(new_main))
    csv_multiset = sorted(int(x) for x in new_deck_csv.split())
    assert len(csv_multiset) == G.DECK_SIZE, "rendered deck.csv is not 60 cards"
    if policy_delta is None:
        assert embedded == csv_multiset == sorted(deck_ids), \
            "embedded/deck.csv/new_deck_ids mismatch"

    payload = G.build_tarball_bytes(main_b, deck_b)
    out_path = G.GENERATED_DIR / f"{gid}.tar.gz"
    write = G.write_tarball_idempotent(out_path, payload)

    return {
        "generated_candidate_id": gid,
        "family_id": src.family_id,
        "admit": admit,
        "operator": operator,
        "parameters": params,
        "deck_changing": policy_delta is None,
        "source_candidate_id": src.candidate_id,
        "source_status": src.status,
        "source_tarball_path": src.tarball_path,
        "source_tarball_sha256": src.tarball_sha256,
        "source_main_sha256": src.main_sha256,
        "source_deck_sha256": src.deck_sha256,
        "parent_candidate_id": src.candidate_id,
        "generation": source_gen + 1,
        "deck_delta": deck_delta,
        "policy_delta": policy_delta,
        "reason": reason,
        "generated_tarball_path": str(out_path.relative_to(REPO)),
        "generated_tarball_sha256": write["sha256"],
        "generated_main_sha256": G.sha256_bytes(main_b),
        "generated_deck_sha256": G.sha256_bytes(deck_b),
        "deck_fingerprint": G.sha256_bytes(deck_b),
        "main_fingerprint": G.sha256_bytes(main_b),
        "tarball_bytes": len(payload),
        "write_status": write["status"],
        "no_upload": True,
    }


def build() -> dict:
    card_db = load_card_db()
    pool = CandidatePool.load()
    gen_by_id = {c.candidate_id: int(getattr(c, "generation", 0) or 0)
                 for c in pool.candidates}

    plan = G.build_plan(pool, card_db)
    sources = {s.candidate_id: s for s in G.eligible_sources(pool)}

    G.GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []

    # --- admitted deck-composition candidates -----------------------------
    for p in plan["planned"]:
        src = sources[p.source_candidate_id]
        entries.append(_build_one(
            src, gen_by_id.get(src.candidate_id, 0), p.operator,
            p.new_deck_ids, p.deck_delta, None, p.reason, p.params,
            p.generated_candidate_id, admit=True))

    # --- NON-admitted regression examples ---------------------------------
    # (1) conservative_policy_weight_delta: deck UNCHANGED, must NOT be admitted.
    pw_src = None
    pw_res = None
    for sid in sorted(sources):
        res = G.policy_weight_delta(sources[sid].main_src)
        if res.applicable:
            pw_src, pw_res = sources[sid], res
            break
    if pw_src is not None:
        gid = (f"generated_{pw_src.family_id}_{G._source_short(pw_src.candidate_id)}"
               f"_{G.OPERATOR_SHORT['conservative_policy_weight_delta']}_v1")
        entries.append(_build_one(
            pw_src, gen_by_id.get(pw_src.candidate_id, 0),
            "conservative_policy_weight_delta", None,
            {"removed": {}, "added": {}}, pw_res.policy_delta, pw_res.reason,
            pw_res.params, gid, admit=False))

    # (2) noop_sentinel: identity (deck unchanged), must be REJECTED as duplicate.
    noop_sid = sorted(sources)[0] if sources else None
    if noop_sid is not None:
        noop_src = sources[noop_sid]
        classified = G.classify_deck(card_db, noop_src.deck_ids)
        res = G.op_noop_sentinel(noop_src.deck_ids, classified, {})
        gid = (f"generated_{noop_src.family_id}_{G._source_short(noop_src.candidate_id)}"
               f"_{G.OPERATOR_SHORT['noop_sentinel']}_v1")
        entries.append(_build_one(
            noop_src, gen_by_id.get(noop_src.candidate_id, 0), "noop_sentinel",
            res.new_deck_ids, res.deck_delta, None, res.reason, res.params,
            gid, admit=False))

    admitted = [e for e in entries if e["admit"]]
    refused = [e for e in entries if e["write_status"] == "differs_exists_refused"]

    return {
        "pass_id": plan["pass_id"],
        "catalog_version": plan["catalog_version"],
        "seed": plan["seed"],
        "budgets": plan["budgets"],
        "eligible_source_ids": plan["eligible_source_ids"],
        "eligible_families": plan["eligible_families"],
        "n_admitted_built": len(admitted),
        "n_regression_built": len(entries) - len(admitted),
        "candidates": entries,
        "root_safety": _root_safety(),
        "guardrails": {
            "no_kaggle_upload": True,
            "no_kaggle_submit": True,
            "no_github_push": True,
            "no_root_mutation": True,
            "no_tarball_overwrite_unless_identical": True,
            "no_tarball_deletion": True,
            "no_promotion_here": True,
            "no_public_reference_source": True,
        },
        "refused_overwrites": [e["generated_candidate_id"] for e in refused],
    }


def _md(rec: dict) -> str:
    L = ["# Pass 42 (Part D) — Generated Candidate Manifest", ""]
    L.append("_LOCAL-only deterministic factory. Tarballs are probation FACTORY "
             "output, NOT a strength or Kaggle claim. No upload/submit/push, no "
             "promotion, no root mutation._")
    L.append("")
    L.append(f"- seed: `{rec['seed']}`")
    L.append(f"- budgets: `{rec['budgets']}`")
    L.append(f"- admitted built: **{rec['n_admitted_built']}** | "
             f"regression examples built: {rec['n_regression_built']}")
    rs = rec["root_safety"]
    L.append(f"- root main.py/deck.csv identical to baseline: "
             f"**{rs['all_identical']}** "
             f"(main.py={rs['main.py']['identical_to_baseline']}, "
             f"deck.csv={rs['deck.csv']['identical_to_baseline']})")
    if rec["refused_overwrites"]:
        L.append(f"- ⚠️ refused overwrites (differing hash): "
                 f"{rec['refused_overwrites']}")
    L.append("")
    L.append("## Candidates")
    L.append("")
    L.append("| generated id | admit | operator | source | gen | deck delta / policy delta | tarball sha (12) | write |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for e in rec["candidates"]:
        delta = e["policy_delta"] if e["policy_delta"] is not None else e["deck_delta"]
        L.append(f"| `{e['generated_candidate_id']}` | "
                 f"{'yes' if e['admit'] else 'NO'} | {e['operator']} | "
                 f"`{e['source_candidate_id']}` | {e['generation']} | "
                 f"`{delta}` | `{e['generated_tarball_sha256'][:12]}` | "
                 f"{e['write_status']} |")
    L.append("")
    L.append("## Lineage detail")
    for e in rec["candidates"]:
        L.append("")
        L.append(f"### `{e['generated_candidate_id']}` "
                 f"({'ADMITTED' if e['admit'] else 'NON-ADMITTED regression'})")
        L.append(f"- operator: `{e['operator']}` params={e['parameters']}")
        L.append(f"- parent: `{e['parent_candidate_id']}` "
                 f"(status {e['source_status']}, generation {e['generation']})")
        L.append(f"- source tarball sha256: `{e['source_tarball_sha256']}`")
        L.append(f"- reason: {e['reason']}")
        if e["policy_delta"] is not None:
            L.append(f"- policy_delta: `{e['policy_delta']}` (deck unchanged)")
        else:
            L.append(f"- deck_delta: `{e['deck_delta']}`")
        L.append(f"- generated tarball: `{e['generated_tarball_path']}` "
                 f"({e['tarball_bytes']} bytes, sha256 "
                 f"`{e['generated_tarball_sha256']}`)")
    L.append("")
    L.append("## Guardrails")
    for k, v in rec["guardrails"].items():
        L.append(f"- {k}: {v}")
    L.append("")
    return "\n".join(L)


def main() -> int:
    rec = build()
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass42_generated_candidates_manifest.json").write_text(
        json.dumps(rec, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8")
    (EXP / "pass42_generated_candidates_manifest.md").write_text(
        _md(rec), encoding="utf-8")

    print(json.dumps({
        "admitted_built": rec["n_admitted_built"],
        "regression_built": rec["n_regression_built"],
        "root_identical_to_baseline": rec["root_safety"]["all_identical"],
        "refused_overwrites": rec["refused_overwrites"],
        "candidates": [(e["generated_candidate_id"], e["write_status"])
                       for e in rec["candidates"]],
    }, indent=2))
    # Hard fail only if a guardrail tripped (root touched / overwrite refused).
    if not rec["root_safety"]["all_identical"]:
        return 1
    if rec["refused_overwrites"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
