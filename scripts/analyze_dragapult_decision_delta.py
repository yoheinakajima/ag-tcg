#!/usr/bin/env python3
"""Pass 19 (Part E) — Dragapult decision-delta analysis.

LOCAL ONLY. NO upload. Reads the Part-D forensic trace
(data/experiments/pass19_dragapult_parent_child_trace.json) and the per-game telemetry
(pass19_dragapult_parent_child_games.jsonl) and answers the eight required questions,
explicitly naming the parent-H2H caveat and the likely role-tag cause (draw_support).

Where the available evidence cannot answer a question (e.g. spread-damage targeting,
which the engine board blob does not expose), this says so explicitly rather than
guessing — per the Pass-19 rule "if evidence is insufficient, say so".
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
TRACE = EXP / "pass19_dragapult_parent_child_trace.json"
GAMES = EXP / "pass19_dragapult_parent_child_games.jsonl"


def _load_games() -> list[dict]:
    if not GAMES.exists():
        return []
    out = []
    for line in GAMES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _tempo(games: list[dict]) -> dict:
    """Average first-attack step + attack count for parent vs child from telemetry."""
    pf, cf, pa, ca = [], [], [], []
    for g in games:
        if not g.get("ok"):
            continue
        ps = g.get("parent_seat")
        cs = 1 - ps if ps is not None else None
        fa = g.get("first_attack_step") or {}
        ac = g.get("attack_count") or {}
        if ps is not None:
            if fa.get(str(ps)) is not None:
                pf.append(fa[str(ps)])
            if fa.get(str(cs)) is not None:
                cf.append(fa[str(cs)])
            if ac.get(str(ps)) is not None:
                pa.append(ac[str(ps)])
            if ac.get(str(cs)) is not None:
                ca.append(ac[str(cs)])

    def avg(xs):
        return round(sum(xs) / len(xs), 1) if xs else None
    return {
        "parent_first_attack_step_avg": avg(pf),
        "child_first_attack_step_avg": avg(cf),
        "parent_attacks_avg": avg(pa),
        "child_attacks_avg": avg(ca),
        "n_games_with_attack_telemetry": len(pf),
    }


def build(trace: dict, games: list[dict]) -> dict:
    dr = trace["decision_replay"]
    gm = trace["games"]
    tempo = _tempo(games)

    search_rows = [r for r in dr["rows"] if r["branch"] == "search_cards"]
    draw_rows = [r for r in dr["rows"] if r["branch"] == "draw_support"]
    search_div = any(r["diverged"] for r in search_rows)
    draw_div = any(r["diverged"] for r in draw_rows)
    control_div = dr["control_divergences"]

    child_wr = gm.get("child_win_rate")
    parent_wr = gm.get("parent_win_rate")

    qs = [
        {"q": "1. Does v1 search better than parent?",
         "answer": "No measurable difference.",
         "evidence": f"In the shared search_to_hand contexts the child and parent make "
                     f"identical choices (search_cards divergences: "
                     f"{sum(1 for r in search_rows if r['diverged'])}/"
                     f"{len(search_rows)}). The search_cards +5 bonus did not change any "
                     f"tested fetch decision; controls (fetch Dreepy before orphaning, "
                     f"fetch payoff when the line is ready) are identical."},
        {"q": "2. Does v1 preserve the Dragapult line better?",
         "answer": "No — the evolution line is preserved equally, but v1 preserves its "
                   "DRAW engine WORSE.",
         "evidence": "Controls show identical preservation of setup_basic / "
                     "evolution_payoff in discard. However, in discard contexts with no "
                     "surplus basic energy, the child discards its own draw_support "
                     "engine (Cheren/Dawn) where the parent keeps it "
                     f"(draw_support divergences: "
                     f"{sum(1 for r in draw_rows if r['diverged'])}/{len(draw_rows)})."},
        {"q": "3. Does v1 over-search or over-thin?",
         "answer": "Mechanism present but NOT observed to change decisions.",
         "evidence": "The search_cards alias enables a +5 over-search bias in "
                     "score_search_target, but it produced no decision delta in the "
                     "tested contexts (the parent already prefers the same fetches). "
                     "There is no behavioral evidence of over-thinning from this alias."},
        {"q": "4. Does v1 delay attacks?",
         "answer": ("Insufficient evidence of a systematic delay."
                    if tempo["n_games_with_attack_telemetry"] else
                    "Insufficient evidence (attack telemetry unavailable)."),
         "evidence": f"From {tempo['n_games_with_attack_telemetry']} games with attack "
                     f"telemetry: parent first-attack step avg "
                     f"{tempo['parent_first_attack_step_avg']} vs child "
                     f"{tempo['child_first_attack_step_avg']}; attacks/game parent "
                     f"{tempo['parent_attacks_avg']} vs child {tempo['child_attacks_avg']}. "
                     f"No large or consistent tempo gap attributable to the role tags; "
                     f"attack-target/spread metadata is not reliably decodable from the "
                     f"engine board blob, so finer tempo claims are withheld."},
        {"q": "5. Does v1 choose worse active/bench setup?",
         "answer": "No.",
         "evidence": f"setup_active and setup_bench controls are identical parent vs "
                     f"child (control divergences: {control_div}). Neither added alias "
                     f"touches the setup scorers."},
        {"q": "6. Does v1 lose parent H2H due to variance or repeatable behavior?",
         "answer": "Repeatable behavior amplified by short-series variance.",
         "evidence": f"The draw_support discard divergence is deterministic and "
                     f"reproducible at the decision layer. Empirically the child wins "
                     f"only {child_wr} of decisive games vs the parent "
                     f"({gm.get('child_wins')}-{gm.get('parent_wins')} over "
                     f"{gm.get('n_games')} games, seat split parent seat0 "
                     f"{gm.get('parent_seat0_wins')} / seat1 "
                     f"{gm.get('parent_seat1_wins')}), consistent with a small "
                     f"repeatable self-harm bias rather than pure noise."},
        {"q": "7. Does v1's aggregate league edge come from beating Water/Raging Bolt "
              "more cleanly?",
         "answer": "Not determinable from this trace alone — directional only.",
         "evidence": "This parent/child trace measures the mirror only. The Pass-18 "
                     "aggregate edge (adj ~0.700) is consistent with field-specialization "
                     "(doing better against non-mirror opponents while losing the "
                     "mirror), but confirming 'beats Water/Raging Bolt more cleanly' "
                     "requires the Pass-19 mini-league + meta sanity (Parts I/J). Treated "
                     "as directional, NOT a Kaggle result."},
        {"q": "8. Which role-tag change likely caused the H2H regression?",
         "answer": "draw_support.",
         "evidence": "draw_support is the ONLY alias that produced a parent->child "
                     "decision divergence (it adds +10 in score_discard_candidate, making "
                     "the child discard its own draw engine). The search_cards alias "
                     "produced no decision delta. Dropping draw_support (the search_only "
                     "ablation) restores the parent's discard behavior."},
    ]

    return {
        "pass": "19", "part": "E", "local_only": True, "upload_performed": False,
        "parent": trace["parent"], "child": trace["child"],
        "deck_identical": trace["deck_identical"],
        "h2h_caveat": (
            "league_dragapult_spread_v1 LOSES the direct parent head-to-head "
            f"(child win rate {child_wr} vs parent {parent_wr}); it must NOT be called "
            "strictly better than the parent. Its Pass-18 aggregate edge is "
            "field-specialized, not a mirror improvement."),
        "likely_h2h_cause": "draw_support role alias (discard self-harm: +10 in "
                            "score_discard_candidate makes v1 discard its own draw "
                            "engine where the parent keeps it).",
        "decision_replay_summary": {
            "n_contexts": dr["n_contexts"], "n_diverged": dr["n_diverged"],
            "diverged_branches": dr["diverged_branches"],
            "search_cards_diverged": search_div, "draw_support_diverged": draw_div,
            "control_divergences": control_div},
        "tempo": tempo,
        "h2h_games": {"child_win_rate": child_wr, "parent_win_rate": parent_wr,
                      "parent_wins": gm.get("parent_wins"),
                      "child_wins": gm.get("child_wins"),
                      "n_games": gm.get("n_games")},
        "questions": qs,
        "disclaimers": [
            "Internal forensic analysis — NOT a Kaggle leaderboard result.",
            "Surrogate/meta comparisons elsewhere are directional only.",
            "No candidate is uploaded or submitted in this pass."],
    }


def _md(d: dict) -> str:
    L = ["# Pass 19 — Dragapult decision-delta analysis (Part E)", "",
         "> LOCAL ONLY — NOT a Kaggle leaderboard. parent = "
         f"`{d['parent']}`, child = `{d['child']}` (deck byte-identical).", "",
         f"**H2H caveat:** {d['h2h_caveat']}", "",
         f"**Likely H2H cause:** {d['likely_h2h_cause']}", "",
         "## Decision-replay summary",
         f"- contexts {d['decision_replay_summary']['n_contexts']}, diverged "
         f"{d['decision_replay_summary']['n_diverged']}, branches "
         f"{d['decision_replay_summary']['diverged_branches']}",
         f"- search_cards diverged: {d['decision_replay_summary']['search_cards_diverged']}"
         f"  draw_support diverged: {d['decision_replay_summary']['draw_support_diverged']}"
         f"  control divergences: {d['decision_replay_summary']['control_divergences']}",
         "", "## Tempo (from game telemetry)",
         f"- parent first-attack avg {d['tempo']['parent_first_attack_step_avg']} vs "
         f"child {d['tempo']['child_first_attack_step_avg']}; attacks/game parent "
         f"{d['tempo']['parent_attacks_avg']} vs child {d['tempo']['child_attacks_avg']} "
         f"(n={d['tempo']['n_games_with_attack_telemetry']})",
         "", "## Eight questions", ""]
    for q in d["questions"]:
        L.append(f"**{q['q']}**")
        L.append(f"- **{q['answer']}**")
        L.append(f"- {q['evidence']}")
        L.append("")
    L.append("## Disclaimers")
    for dc in d["disclaimers"]:
        L.append(f"- {dc}")
    L.append("")
    return "\n".join(L)


def main() -> int:
    trace = json.loads(TRACE.read_text(encoding="utf-8"))
    games = _load_games()
    d = build(trace, games)
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass19_dragapult_decision_delta.json").write_text(
        json.dumps(d, indent=2), encoding="utf-8")
    (EXP / "pass19_dragapult_decision_delta.md").write_text(_md(d), encoding="utf-8")
    print("decision-delta written; likely cause:", d["likely_h2h_cause"][:60])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
