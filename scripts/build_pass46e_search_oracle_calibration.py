#!/usr/bin/env python3
"""PASS 46E — Part D: cg Search oracle calibration vs Pass-46C full traces.

For a bounded, family-balanced set of decision frames drawn from the Pass-46C
trace panel, take the *actual* selected action, evaluate it with the search
oracle, and compare the predicted one-step post-state signature to the ACTUAL
next frame. Classify each as exact_match / partial_match / mismatch / unsupported
/ timed_out / error, and aggregate.

LOCAL / READ-ONLY / DIAGNOSTIC. No production mutation, no Object Storage write,
no candidate generation, no Kaggle upload. Honest by construction: a weak or
mismatched calibration forces a non-ready decision downstream.

Runnable standalone (writes artifacts) and importable
(``run_calibration() -> dict``).
"""
from __future__ import annotations

import glob
import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.analysis import search_oracle as O  # noqa: E402

EXP = REPO / "data" / "experiments"
TRACES = EXP / "pass46c_traces"

CAVEATS = [
    "READ-ONLY / LOCAL / DIAGNOSTIC: production Object Storage was not mutated.",
    "No production tick, candidate generation, promotion, queue, upload, or republish.",
    "cg Search needs predicted hidden zones (opponent deck/hand/prize, your prize); "
    "those are fabricated placeholder basic-Pokémon IDs — an assumption, not the "
    "real hidden state.",
    "Only objective/visible fields are compared (counts, visible active ids/hp, "
    "turn, result, stadium) — never hidden hand/deck contents.",
    "No exact-damage / lethal / missed-KO / best-action claim is made here.",
    "Public references are BENCHMARK-ONLY; their frames are calibration inputs, not "
    "candidate sources.",
]

# SelectContext / OptionType integer codes (see cg/_sdk api.py).
_CTX_TO_HAND, _CTX_DISCARD, _CTX_MAIN = 7, 8, 0
_CTX_SETUP = {1, 2}
_CTX_ATTACK = 35
_OPT = {"play": 7, "attach": 8, "discard": 11, "attack": 13, "end": 14}
_OPT_NAMES = {  # raw traces sometimes carry string option type names
    "play": "Play", "attach": "Attach", "discard": "Discard",
    "attack": "Attack", "end": "End",
}


def write_pair(stem: str, data: dict, title: str, body: str) -> None:
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / f"{stem}.json").write_text(json.dumps(data, indent=2, default=str) + "\n",
                                      encoding="utf-8")
    head = ("# " + title + "\n\n_Pass 46E — cg Search oracle calibration. READ-ONLY / "
            "LOCAL / DIAGNOSTIC. Predicted one-step post-states vs actual next "
            "frames; hidden zones are assumptions. No generation / promotion / "
            "upload / tick._\n\n")
    caveat = "## Caveats\n" + "".join(f"- {c}\n" for c in CAVEATS) + "\n"
    (EXP / f"{stem}.md").write_text(head + caveat + body + "\n", encoding="utf-8")


def _opt_type(option) -> object:
    if isinstance(option, dict):
        return option.get("type")
    return None


def _is_type(option, key: str) -> bool:
    t = _opt_type(option)
    return t == _OPT[key] or t == _OPT_NAMES[key]


def classify_family(select: dict, selected: list[int]) -> str:
    """Coarse action family from the select context + chosen option type(s)."""
    if not isinstance(select, dict):
        return "other"
    ctx = select.get("context")
    opts = select.get("option") or []
    chosen = [opts[i] for i in selected if isinstance(i, int) and 0 <= i < len(opts)]
    if ctx == _CTX_ATTACK or any(_is_type(o, "attack") for o in chosen):
        return "attack"
    if any(_is_type(o, "attach") for o in chosen):
        return "attach"
    if ctx == _CTX_TO_HAND or select.get("deck") is not None:
        return "search_to_hand"
    if ctx == _CTX_DISCARD or any(_is_type(o, "discard") for o in chosen):
        return "discard"
    if any(_is_type(o, "play") for o in chosen):
        return "play"
    if any(_is_type(o, "end") for o in chosen):
        return "end"
    if ctx in _CTX_SETUP:
        return "setup"
    if len(opts) <= 1:
        return "low_choice"
    if ctx == _CTX_MAIN:
        return "main_mixed"
    return "other"


def role_bucket(role: object) -> str:
    r = str(role or "").lower()
    if "public_ref" in r or "reference" in r:
        return "public_reference"
    if "parent" in r or "anchor" in r:
        return "internal_parent"
    return "internal_candidate"


def _next_current(steps: list, i: int):
    """The actual post-state ``current`` from the ACTIVE seat at step ``i+1``.

    ONLY the ACTIVE seat's observation is accepted — the INACTIVE seat carries a
    STALE observation from its last turn (wrong ``turn`` / counts). If no ACTIVE
    seat exposes a ``current`` at ``i+1`` we return ``None`` so the frame is
    SKIPPED rather than calibrated against stale data (airtight causality; never
    fall back to a non-ACTIVE current).
    """
    if i + 1 >= len(steps):
        return None
    nxt = steps[i + 1]
    if not isinstance(nxt, list):
        return None
    for o in nxt:
        if not isinstance(o, dict):
            continue
        obs = o.get("observation")
        if not isinstance(obs, dict) or not isinstance(obs.get("current"), dict):
            continue
        if str(o.get("status", "")).upper() == "ACTIVE":
            return obs["current"]
    return None


def _select_frames(steps: list, a_seat: int, role_a, role_b,
                   per_family: int) -> list[dict]:
    """Pick family-balanced ACTIVE decision frames with a legal index action."""
    picked: list[dict] = []
    counts: dict[str, int] = {}
    for i, st in enumerate(steps[:-1]):
        if not isinstance(st, list):
            continue
        for seat, o in enumerate(st):
            if not isinstance(o, dict):
                continue
            # ACTIVE-only: the INACTIVE seat carries a STALE observation/action that
            # did NOT produce the next state used as ground truth (breaks causality).
            if str(o.get("status", "")).upper() != "ACTIVE":
                continue
            obs = o.get("observation")
            if not isinstance(obs, dict) or not obs.get("search_begin_input"):
                continue
            sel = obs.get("select")
            cur = obs.get("current")
            if not isinstance(sel, dict) or not isinstance(cur, dict):
                continue
            action = o.get("action")
            n_opt = len(sel.get("option") or [])
            if not O._is_index_action(action, n_opt, sel.get("minCount"),
                                      sel.get("maxCount")):
                continue
            gt = _next_current(steps, i)
            if gt is None:
                continue
            fam = classify_family(sel, action)
            if counts.get(fam, 0) >= per_family:
                continue
            counts[fam] = counts.get(fam, 0) + 1
            role = role_a if seat == a_seat else role_b
            picked.append({
                "step": i, "seat": seat, "family": fam,
                "role_bucket": role_bucket(role),
                "frame": o, "selected": list(action),
                "ground_truth_current": gt,
            })
    return picked


def run_calibration(per_family_per_trace: int = 3, total_cap: int = 160,
                    timeout_s: float = 6.0) -> dict:
    trace_paths = sorted(glob.glob(str(TRACES / "*.json.gz")))
    selected: list[dict] = []
    per_trace_meta = []
    for tp in trace_paths:
        try:
            d = json.loads(__import__("gzip").open(tp).read())
        except Exception as exc:  # noqa: BLE001
            per_trace_meta.append({"trace": Path(tp).name,
                                   "error": f"{type(exc).__name__}"})
            continue
        steps = d.get("steps") or []
        frames = _select_frames(steps, int(d.get("a_seat", 0)),
                                d.get("role_a"), d.get("role_b"),
                                per_family_per_trace)
        for f in frames:
            f["trace"] = Path(tp).name
            f["matchup"] = d.get("id")
        selected.extend(frames)
        per_trace_meta.append({"trace": Path(tp).name, "n_frames": len(frames)})
        if len(selected) >= total_cap:
            selected = selected[:total_cap]
            break

    items = [(f["frame"], f["selected"]) for f in selected]
    results = O.evaluate_actions_batch(items, timeout_s=timeout_s)

    rows = []
    elapseds = []
    for f, res in zip(selected, results):
        outcome = res.outcome
        pred_sig = outcome.post_signature if outcome else None
        gt_sig = O.signature_from_current(f["ground_truth_current"])
        if outcome and outcome.timed_out:
            cls = "timed_out"
        elif not res.ok or pred_sig is None:
            cls = "error" if (outcome and outcome.error) else "unsupported"
        else:
            cmp = O.compare_signatures(pred_sig, gt_sig)
            cls = cmp["classification"]
        if outcome and isinstance(outcome.elapsed_s, (int, float)):
            elapseds.append(float(outcome.elapsed_s))
        rows.append({
            "trace": f["trace"], "step": f["step"], "seat": f["seat"],
            "family": f["family"], "role_bucket": f["role_bucket"],
            "selected": f["selected"], "classification": cls,
            "supported_level": res.supported_level,
            "elapsed_s": outcome.elapsed_s if outcome else None,
            "warnings": res.warnings,
            "compare": (O.compare_signatures(pred_sig, gt_sig)
                        if (res.ok and pred_sig is not None) else None),
        })

    def _tally(key_fn):
        agg: dict = {}
        for r in rows:
            k = key_fn(r)
            b = agg.setdefault(k, {})
            b[r["classification"]] = b.get(r["classification"], 0) + 1
        return agg

    classes = ["exact_match", "partial_match", "mismatch", "unsupported",
               "timed_out", "error", "uncomparable"]
    overall = {c: sum(1 for r in rows if r["classification"] == c) for c in classes}
    n = len(rows)
    supported = sum(overall[c] for c in ("exact_match", "partial_match"))
    decisive_attempts = sum(overall[c] for c in
                            ("exact_match", "partial_match", "mismatch"))
    exact_rate = (overall["exact_match"] / decisive_attempts) if decisive_attempts else 0.0
    mismatch_rate = (overall["mismatch"] / decisive_attempts) if decisive_attempts else 0.0

    supported_level_breakdown = {}
    for r in rows:
        supported_level_breakdown[r["supported_level"]] = \
            supported_level_breakdown.get(r["supported_level"], 0) + 1

    data = {
        "pass": "46e", "part": "D", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "tick_executed": False,
        "candidate_generated": False,
        "n_traces": len(trace_paths), "per_trace": per_trace_meta,
        "frames_attempted": n, "frames_supported": supported,
        "decisive_attempts": decisive_attempts,
        "overall_classification": overall,
        "exact_rate_of_decisive": round(exact_rate, 4),
        "mismatch_rate_of_decisive": round(mismatch_rate, 4),
        "supported_level_breakdown": supported_level_breakdown,
        "by_family": _tally(lambda r: r["family"]),
        "by_role_bucket": _tally(lambda r: r["role_bucket"]),
        "by_trace": _tally(lambda r: r["trace"]),
        "elapsed_stats": _stats(elapseds),
        "rows": rows,
        "unsupported_claims": O.unsupported_search_claims(),
    }

    body = (
        f"## Aggregate\n"
        f"- frames_attempted: **{n}**\n"
        f"- frames_supported (exact+partial): **{supported}**\n"
        f"- decisive_attempts (exact+partial+mismatch): **{decisive_attempts}**\n"
        f"- exact_rate_of_decisive: **{exact_rate:.3f}**\n"
        f"- mismatch_rate_of_decisive: **{mismatch_rate:.3f}**\n\n"
        "## Classification counts\n"
        + "".join(f"- `{c}`: {overall[c]}\n" for c in classes)
        + "\n## By action family\n"
        + "".join(f"- `{k}`: {v}\n" for k, v in sorted(data["by_family"].items()))
        + "\n## By role bucket\n"
        + "".join(f"- `{k}`: {v}\n" for k, v in sorted(data["by_role_bucket"].items()))
        + "\n## Supported-level breakdown\n"
        + "".join(f"- `{k}`: {v}\n" for k, v in supported_level_breakdown.items())
    )
    write_pair("pass46e_search_oracle_calibration", data,
               "Pass 46E — Part D: cg Search oracle calibration", body)
    return data


def _stats(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0, "median": None, "p90": None, "p99": None, "max": None}
    s = sorted(xs)

    def pct(p):
        if len(s) == 1:
            return s[0]
        idx = min(len(s) - 1, int(round(p * (len(s) - 1))))
        return s[idx]
    return {"n": len(s), "median": round(statistics.median(s), 5),
            "p90": round(pct(0.90), 5), "p99": round(pct(0.99), 5),
            "max": round(s[-1], 5)}


if __name__ == "__main__":
    out = run_calibration()
    print(json.dumps({k: out[k] for k in (
        "frames_attempted", "frames_supported", "exact_rate_of_decisive",
        "mismatch_rate_of_decisive", "overall_classification")}, indent=2))
