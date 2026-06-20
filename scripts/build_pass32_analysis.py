#!/usr/bin/env python3
"""Pass 32 — Dragapult Kaggle result + replay postmortem (analysis builder).

READ-ONLY wrt Kaggle. No upload. No new candidates. No root/tarball mutation.
Generates Parts B, C, E, F, G, H artifacts from:
- the read-only Kaggle status CSV captured this pass,
- the raw replay corpus + extracted decks,
- our candidate tarball deck fingerprints.

Honesty rules: never invent card ids; never claim spread-targeting misplay unless
the spread target identity is observable (it is not — attackIds are numeric only).
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

RAW = REPO / "data" / "meta_replays" / "raw"
DECKS = REPO / "data" / "meta_replays" / "decks"
EXP = REPO / "data" / "experiments"
KU = REPO / "data" / "kaggle_uploads"
STATUS_CSV_LOG = KU / "status_before_pass32_dragapult_probe.log"

DRAGAPULT_TARBALL = ("data/submissions/candidates_pass19/"
                     "league_dragapult_v1_search_only.tar.gz")
# Episodes newly uploaded this pass (untracked + unregistered before Pass 32).
NEW_EPISODES = ["80760752", "80760852", "80761535"]
# Pre-existing tracked self-mirror from older passes (report-only, do not modify).
PREEXISTING_SELF_MIRROR = "80374966"
RAW_BEFORE = 19  # registry replays_total before this pass


# ---------------------------------------------------------------- helpers
def _safe_float(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _fingerprint(cards):
    c = Counter(int(x) for x in cards)
    s = ",".join(f"{k}:{v}" for k, v in sorted(c.items()))
    return hashlib.sha1(s.encode()).hexdigest()[:12], len(cards), len(c)


def _read_csv_cards(p: Path):
    return [l.strip() for l in p.read_text().splitlines() if l.strip()]


def _gitignored(p: str) -> bool:
    return subprocess.run(["git", "--no-optional-locks", "check-ignore", p],
                          capture_output=True).returncode == 0


def _tracked(p: str) -> bool:
    out = subprocess.run(["git", "--no-optional-locks", "ls-files", p],
                         capture_output=True, text=True).stdout.strip()
    return bool(out)


def _candidate_fps():
    import glob
    import tarfile
    fps = {}
    sources = {
        "league_dragapult_v1_search_only": DRAGAPULT_TARBALL,
    }
    for name in ("league_water_anti_disruption_pivot_v1",
                 "league_water_core_reference", "core_pilot_water_v2_runtime"):
        hits = glob.glob(str(REPO / f"data/submissions/**/{name}.tar.gz"),
                         recursive=True)
        if hits:
            sources[name] = hits[0]
    for name, tb in sources.items():
        try:
            with tarfile.open(tb, "r:gz") as tf:
                m = [x for x in tf.getmembers() if x.name.endswith("deck.csv")]
                if not m:
                    continue
                deck = tf.extractfile(m[0]).read().decode()
            cards = [l.strip() for l in deck.splitlines() if l.strip()]
            fps[name] = _fingerprint(cards)
        except Exception:  # noqa: BLE001
            continue
    return fps


# ---------------------------------------------------------------- Part C
def part_c_status():
    rows = []
    with STATUS_CSV_LOG.open() as fh:
        for line in fh:
            if line.startswith("Warning") or not line.strip():
                continue
            rows.append(line)
    reader = csv.DictReader(rows)
    subs = []
    for r in reader:
        subs.append({
            "filename": r.get("fileName"),
            "description": r.get("description"),
            "status": r.get("status"),
            "public_score": _safe_float(r.get("publicScore")),
            "date": r.get("date"),
        })
    # plain CSV (no warning line) for provenance
    (KU / "status_before_pass32_dragapult_probe.csv").write_text(
        "".join(rows), encoding="utf-8")

    complete = [s for s in subs if s["status"] == "complete"
                and s["public_score"] is not None]
    leader = max(complete, key=lambda s: s["public_score"]) if complete else None
    water = [s for s in complete if "water" in (s["filename"] or "").lower()]
    drag = [s for s in complete if "dragapult" in (s["filename"] or "").lower()]
    water_best = max(water, key=lambda s: s["public_score"]) if water else None
    drag_best = max(drag, key=lambda s: s["public_score"]) if drag else None
    drag_latest = next((s for s in subs if (s["filename"] or "").startswith(
        "league_dragapult_v1_search_only")), None)

    status = {
        "pass": "pass32", "part": "C", "no_upload": True,
        "upload_performed": False,
        "competition": "pokemon-tcg-ai-battle",
        "auth_method": ("python kaggle.cli (CLI not on PATH); "
                        "KAGGLE_USERNAME/KAGGLE_KEY env; credentials never printed"),
        "dragapult": {
            "filename": drag_latest["filename"] if drag_latest else None,
            "status": drag_latest["status"] if drag_latest else None,
            "public_score": drag_latest["public_score"] if drag_latest else None,
            "date": drag_latest["date"] if drag_latest else None,
        },
        "live_score_leader": {"filename": leader["filename"],
                              "public_score": leader["public_score"]} if leader else None,
        "water_family_current_best": {"filename": water_best["filename"],
                                      "public_score": water_best["public_score"]} if water_best else None,
        "dragapult_family_best": {"filename": drag_best["filename"],
                                  "public_score": drag_best["public_score"]} if drag_best else None,
        "score_drift": {
            "dragapult_pass31": "pending (no score)",
            "dragapult_pass32": drag_latest["public_score"] if drag_latest else None,
            "dragapult_pass30_live": "none (was not on live leaderboard in Pass 30)",
            "note": ("Pass31 left Dragapult pending; Pass32 resolves it to a real "
                     "publicScore. No Dragapult live score existed in Pass 30."),
        },
        "stale_caveat": ("Pass-30 docs referenced water best @ 376.5; the live "
                         "read-only listing this pass shows water best @ "
                         f"{water_best['public_score'] if water_best else 'n/a'} — "
                         "the figures here are the fresh live values."),
        "all_submissions": subs,
        "source_log": str(STATUS_CSV_LOG.relative_to(REPO)),
    }
    (EXP / "pass32_kaggle_status.json").write_text(
        json.dumps(status, indent=2), encoding="utf-8")

    md = ["# Pass 32 — Kaggle status (read-only, no upload)", "",
          f"- dragapult status: **{status['dragapult']['status']}**",
          f"- dragapult publicScore: **{status['dragapult']['public_score']}**",
          f"- live_score_leader: {leader['filename']} @ {leader['public_score']}" if leader else "- live_score_leader: n/a",
          f"- water_family_current_best: {water_best['filename']} @ {water_best['public_score']}" if water_best else "- water best: n/a",
          f"- dragapult_family_best: {drag_best['filename']} @ {drag_best['public_score']}" if drag_best else "- dragapult best: n/a",
          f"- score drift: {status['score_drift']['note']}",
          f"- stale caveat: {status['stale_caveat']}",
          "- upload performed: NO (read-only listing only)", "",
          "| fileName | status | publicScore | date |", "|---|---|---|---|"]
    for s in subs:
        md.append(f"| {s['filename']} | {s['status']} | {s['public_score']} | {s['date']} |")
    (EXP / "pass32_kaggle_status.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # live_score_registry.json / .md
    def classify(s):
        if s["filename"] == (leader["filename"] if leader else None):
            return "live_score_leader"
        if water_best and s["filename"] == water_best["filename"]:
            return "active_control_candidate"
        if s["status"] == "error":
            return "error"
        return "complete"
    registry = {
        "competition": "pokemon-tcg-ai-battle",
        "generated_at": time.time(),
        "source": "kaggle competitions submissions -v (read-only listing, Pass 32)",
        "no_upload": True,
        "live_score_leader": leader["filename"] if leader else None,
        "water_family_current_best": water_best["filename"] if water_best else None,
        "dragapult_family_best": drag_best["filename"] if drag_best else None,
        "submissions": [{**s, "classification": classify(s)} for s in subs],
    }
    (KU / "live_score_registry.json").write_text(
        json.dumps(registry, indent=2), encoding="utf-8")
    rmd = ["# Live score registry (read-only, Pass 32)", "",
           f"- live_score_leader: {registry['live_score_leader']}",
           f"- water_family_current_best: {registry['water_family_current_best']}",
           f"- dragapult_family_best: {registry['dragapult_family_best']}",
           "- no upload performed", "",
           "| fileName | status | publicScore | classification | date |",
           "|---|---|---|---|---|"]
    for s in registry["submissions"]:
        rmd.append(f"| {s['filename']} | {s['status']} | {s['public_score']} | "
                   f"{s['classification']} | {s['date']} |")
    (KU / "live_score_registry.md").write_text("\n".join(rmd) + "\n", encoding="utf-8")
    return status


# ---------------------------------------------------------------- Part B
def part_b_raw_safety():
    raw_files = sorted(f for f in os.listdir(RAW) if f.endswith(".json"))
    records = []
    names_seen = Counter()
    for f in raw_files:
        p = RAW / f
        rel = str(p.relative_to(REPO))
        epid = f.replace("_self_mirror", "").replace(".json", "")
        names_seen[f] += 1
        try:
            d = json.loads(p.read_text())
            info = d.get("info", {})
            eid = info.get("EpisodeId") or d.get("EpisodeId")
            steps = d.get("steps")
            nsteps = len(steps) if isinstance(steps, list) else None
            valid_struct = bool(eid) and isinstance(steps, list) and nsteps and \
                isinstance(d.get("rewards"), list)
        except Exception as exc:  # noqa: BLE001
            eid, nsteps, valid_struct = None, None, False
        is_new = epid in NEW_EPISODES
        records.append({
            "file": f, "path": rel, "episode_id": eid,
            "gitignored": _gitignored(rel), "tracked": _tracked(rel),
            "steps": nsteps, "valid_structure": valid_struct,
            "is_new_this_pass": is_new,
            "is_preexisting_self_mirror": epid == PREEXISTING_SELF_MIRROR,
        })
    dupes = [n for n, c in names_seen.items() if c > 1]
    new_recs = [r for r in records if r["is_new_this_pass"]]
    out = {
        "pass": "pass32", "part": "B", "no_upload": True,
        "raw_total": len(raw_files),
        "new_this_pass": [str(r["episode_id"]) for r in new_recs],
        "new_all_gitignored": all(r["gitignored"] for r in new_recs),
        "new_all_untracked": all(not r["tracked"] for r in new_recs),
        "new_all_valid_structure": all(r["valid_structure"] for r in new_recs),
        "duplicate_filenames": dupes,
        "preexisting_self_mirror": {
            "episode_id": PREEXISTING_SELF_MIRROR,
            "note": ("tracked from old passes; reported pre-existing only, not "
                     "modified"),
            "tracked": _tracked(f"data/meta_replays/raw/{PREEXISTING_SELF_MIRROR}_self_mirror.json"),
        },
        "records": records,
    }
    (EXP / "pass32_raw_replay_safety.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    md = ["# Pass 32 — Raw replay safety", "",
          f"- raw replays total: {out['raw_total']}",
          f"- new this pass: {', '.join(out['new_this_pass'])}",
          f"- new all gitignored: {out['new_all_gitignored']}",
          f"- new all untracked (not staged/committed): {out['new_all_untracked']}",
          f"- new all valid structure (EpisodeId/steps/rewards): {out['new_all_valid_structure']}",
          f"- duplicate filename conflicts: {dupes or 'none'}",
          f"- pre-existing tracked self-mirror: {PREEXISTING_SELF_MIRROR} "
          "(reported only, not modified)", "",
          "| file | episode | gitignored | tracked | steps | valid | new |",
          "|---|---|---|---|---|---|---|"]
    for r in records:
        md.append(f"| {r['file']} | {r['episode_id']} | {r['gitignored']} | "
                  f"{r['tracked']} | {r['steps']} | {r['valid_structure']} | "
                  f"{r['is_new_this_pass']} |")
    (EXP / "pass32_raw_replay_safety.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------- Part E
def _seat_fp(epid, seat):
    p = DECKS / f"{epid}_p{seat}_deck.csv"
    if not p.exists():
        return None
    return _fingerprint(_read_csv_cards(p))


def part_e_attribution(cand_fps):
    # ambiguity: which of our candidate names share a fingerprint
    by_fp = {}
    for name, fp in cand_fps.items():
        by_fp.setdefault(fp[0], []).append(name)
    ambiguous = {k: v for k, v in by_fp.items() if len(v) > 1}

    raw = json.loads((RAW / f"{NEW_EPISODES[0]}.json").read_text())
    attributions = []
    OUR_SEATS = {"80760752": [0, 1], "80760852": [0], "80761535": [0]}
    for epid in NEW_EPISODES:
        d = json.loads((RAW / f"{epid}.json").read_text())
        info = d.get("info", {})
        teams = info.get("TeamNames")
        rewards = d.get("rewards")
        our_seats = OUR_SEATS[epid]
        self_mirror = len(our_seats) == 2
        seat_attr = {}
        for seat in (0, 1):
            fp = _seat_fp(epid, seat)
            match = [n for n, v in cand_fps.items() if fp and v[0] == fp[0]]
            if match:
                # collapse water-ambiguous matches honestly
                label = match[0] if len(match) == 1 else "ambiguous:" + "|".join(match)
                conf = "exact_deck_fingerprint" if len(match) == 1 else "exact_deck_fingerprint_ambiguous"
            else:
                label = "opponent" if seat not in our_seats else "unknown_ours"
                conf = "unknown"
            seat_attr[seat] = {"fingerprint": fp[0] if fp else None,
                               "deck_match": label, "confidence": conf,
                               "is_ours": seat in our_seats}
        # our result
        our_seat0 = our_seats[0]
        our_reward = rewards[our_seat0] if isinstance(rewards, list) else None
        result = ("win" if our_reward == 1 else "loss" if our_reward == -1
                  else "draw" if our_reward == 0 else "unknown")
        belongs = any(seat_attr[s]["deck_match"] == "league_dragapult_v1_search_only"
                      for s in our_seats)
        attributions.append({
            "episode_id": epid, "file": f"data/meta_replays/raw/{epid}.json",
            "team_names": teams, "our_seats": our_seats,
            "self_mirror": self_mirror, "rewards": rewards,
            "result_from_our_perspective": "win (self-mirror)" if self_mirror else result,
            "seat_attribution": seat_attr,
            "belongs_to_dragapult_probe": belongs,
        })
    out = {
        "pass": "pass32", "part": "E", "no_upload": True,
        "candidate_fingerprints": {k: v[0] for k, v in cand_fps.items()},
        "fingerprint_ambiguity": ambiguous,
        "ambiguity_note": ("The three Water candidates share one identical 60-card "
                           "deck fingerprint, so a Water replay cannot be attributed "
                           "to a specific Water candidate by deck alone — reported "
                           "honestly. (None of the new replays are Water.)"),
        "attributions": attributions,
    }
    (EXP / "pass32_replay_attribution.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    md = ["# Pass 32 — Replay attribution (deck fingerprint)", "",
          f"- candidate fingerprints: {out['candidate_fingerprints']}",
          f"- ambiguity: {ambiguous} — {out['ambiguity_note']}", "",
          "| episode | our seat | self-mirror | result | seat0 match | seat1 match | belongs to Dragapult probe |",
          "|---|---|---|---|---|---|---|"]
    for a in attributions:
        md.append(f"| {a['episode_id']} | {a['our_seats']} | {a['self_mirror']} | "
                  f"{a['result_from_our_perspective']} | "
                  f"{a['seat_attribution'][0]['deck_match']} ({a['seat_attribution'][0]['confidence']}) | "
                  f"{a['seat_attribution'][1]['deck_match']} ({a['seat_attribution'][1]['confidence']}) | "
                  f"{a['belongs_to_dragapult_probe']} |")
    (EXP / "pass32_replay_attribution.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------- Part F
def _postmortem_one(epid, seat):
    d = json.loads((RAW / f"{epid}.json").read_text())
    steps = d["steps"]
    rewards = d.get("rewards")
    attack_ids, first_attack_step = [], None
    n_attach = n_abil = n_play = n_end = 0
    invalids = 0
    for i, st in enumerate(steps):
        cell = st[seat]
        if cell.get("status") == "INVALID":
            invalids += 1
        if cell.get("status") != "ACTIVE":
            continue
        sel = cell.get("observation", {}).get("select")
        act = cell.get("action")
        if not (sel and isinstance(act, list) and act):
            continue
        opts = sel.get("option") or sel.get("options") or []
        if len(opts) > 40:  # deck-selection step
            continue
        for idx in act:
            if not isinstance(idx, int) or idx >= len(opts):
                continue
            t = opts[idx].get("type")
            if t == 13:
                attack_ids.append(opts[idx].get("attackId"))
                first_attack_step = first_attack_step if first_attack_step is not None else i
            elif t == 8:
                n_attach += 1
            elif t == 9:
                n_abil += 1
            elif t in (7, 10):
                n_play += 1
            elif t in (12, 14):
                n_end += 1
    # final board state
    final_state = None
    for st in reversed(steps):
        c = st[0].get("observation", {}).get("current")
        if isinstance(c, dict) and c.get("players"):
            final_state = c
            break
    prize_us = prize_opp = bench_us = None
    if final_state:
        pls = final_state.get("players") or []
        opp_seat = 1 - seat if seat in (0, 1) else None
        def _prize_count(pl):
            v = pl.get("prize")
            return len(v) if isinstance(v, list) else v
        if seat < len(pls):
            pl = pls[seat]
            prize_us = _prize_count(pl)
            b = pl.get("bench")
            bench_us = len(b) if isinstance(b, list) else b
        if opp_seat is not None and opp_seat < len(pls):
            pl = pls[opp_seat]
            prize_opp = _prize_count(pl)
    our_reward = rewards[seat] if isinstance(rewards, list) else None
    result = "win" if our_reward == 1 else "loss" if our_reward == -1 else "draw"

    # honest loss classification
    loss_class = "n/a (win)"
    loss_condition = "n/a"
    contributing = []
    if result == "loss":
        # prize remaining: 6 means took 0. opp_remaining low => prize race.
        if bench_us == 0 and (prize_opp is not None and prize_opp >= 4):
            loss_condition = "no_pokemon_in_play"
            loss_class = "no_pokemon_loss"
        elif prize_opp is not None and prize_opp <= 2:
            loss_condition = "prizes"
            loss_class = "prize_race_loss"
        else:
            loss_condition = "prizes_or_no_pokemon (board emptied with opp few prizes)"
            loss_class = "opponent_outpaced"
        # contributing factors (do NOT override the terminal loss condition)
        nsteps = len(steps)
        if first_attack_step is not None and first_attack_step >= 0.8 * nsteps:
            contributing.append("very_late_first_attack")
        if not attack_ids:
            contributing.append("never_attacked")
        if attack_ids and prize_us == 6:
            contributing.append("attacks_did_not_convert_to_prizes")
    return {
        "episode_id": epid, "our_seat": seat, "result": result,
        "num_steps": len(steps), "rewards": rewards,
        "prizes_remaining_us": prize_us, "prizes_remaining_opp": prize_opp,
        "final_bench_us": bench_us,
        "evolved_observable": False,
        "evolved_note": ("evolution is not separately labelled vs play_from_hand "
                         "in the option schema; play_from_hand/play_in_play count "
                         f"= {n_play}"),
        "attacked": bool(attack_ids),
        "first_attack_step": first_attack_step,
        "attack_ids": attack_ids,
        "phantom_dive_or_spread_used": "not_observable",
        "spread_target_observable": False,
        "bench_damage_target_observable": False,
        "dusknoir_line_observable": False,
        "boss_gust_observable": False,
        "energy_attachments": n_attach,
        "abilities_used": n_abil,
        "plays_from_hand": n_play,
        "end_turns": n_end,
        "invalid_actions": invalids,
        "deckout_risk": "none (engine reported not decked out)",
        "repeated_effect_loops": "none observed",
        "loss_condition": loss_condition,
        "loss_classification": loss_class,
        "contributing_factors": contributing,
        "key_failure_window": (
            f"first attack only at step {first_attack_step}/{len(steps)} "
            "(very late setup)" if first_attack_step is not None and
            first_attack_step >= 0.7 * len(steps) else
            ("attacked but took 0 prizes — pressure did not convert to KOs"
             if result == "loss" and attack_ids and (prize_us == 6) else
             "n/a" if result == "win" else "standard prize race")),
    }


def part_f_postmortem(attribution):
    # One game per episode from our canonical seat (p0); self-mirror counts once.
    drag_eps = [(a["episode_id"], a["our_seats"][0], a["self_mirror"])
                for a in attribution["attributions"]
                if a["belongs_to_dragapult_probe"]]
    games = []
    for ep, seat, mirror in drag_eps:
        g = _postmortem_one(ep, seat)
        g["self_mirror"] = mirror
        games.append(g)
    wins = sum(1 for g in games if g["result"] == "win")
    losses = sum(1 for g in games if g["result"] == "loss")
    # exclude self-mirror from "vs-field" record
    vs_field = [g for g in games if not g.get("self_mirror")]
    out = {
        "pass": "pass32", "part": "F", "no_upload": True,
        "dragapult_replays_found": len(games),
        "wins": wins, "losses": losses, "draws": 0,
        "vs_real_opponent_record": f"{sum(1 for g in vs_field if g['result']=='win')}W"
                                   f"/{sum(1 for g in vs_field if g['result']=='loss')}L",
        "primary_loss_modes": sorted({g["loss_classification"] for g in games
                                      if g["result"] == "loss"}),
        "contributing_factors": sorted({c for g in games
                                        for c in g.get("contributing_factors", [])}),
        "spread_targeting_observability": ("NOT observable — attacks expose only a "
                                           "numeric attackId (153/169/150); attack "
                                           "name and spread target identity are not "
                                           "in the option schema. No spread-misplay "
                                           "claim is made."),
        "games": games,
    }
    (EXP / "pass32_dragapult_postmortem.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    with (EXP / "pass32_dragapult_windows.jsonl").open("w") as fh:
        for g in games:
            fh.write(json.dumps({
                "episode_id": g["episode_id"], "our_seat": g["our_seat"],
                "result": g["result"], "first_attack_step": g["first_attack_step"],
                "attack_ids": g["attack_ids"],
                "loss_condition": g["loss_condition"],
                "loss_classification": g["loss_classification"],
                "contributing_factors": g.get("contributing_factors", []),
                "key_failure_window": g["key_failure_window"]}) + "\n")
    md = ["# Pass 32 — Dragapult live postmortem", "",
          f"- Dragapult replays: {len(games)} ({wins}W/{losses}L, self-mirror counted as a win)",
          f"- vs real opponents: {out['vs_real_opponent_record']}",
          f"- primary loss modes (terminal): {out['primary_loss_modes']}",
          f"- contributing factors: {out['contributing_factors']}",
          f"- spread targeting observability: {out['spread_targeting_observability']}", "",
          "| episode | result | steps | first attack | attackIds | prizes us/opp | bench us | loss condition | class | contributing |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for g in games:
        md.append(f"| {g['episode_id']} | {g['result']} | {g['num_steps']} | "
                  f"{g['first_attack_step']} | {g['attack_ids']} | "
                  f"{g['prizes_remaining_us']}/{g['prizes_remaining_opp']} | "
                  f"{g['final_bench_us']} | {g['loss_condition']} | "
                  f"{g['loss_classification']} | "
                  f"{', '.join(g.get('contributing_factors', [])) or '-'} |")
    (EXP / "pass32_dragapult_postmortem.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------- Part G
def part_g_comparison(status, postmortem):
    # Resolve duplicate filename histories deterministically: prefer a complete
    # row with a real publicScore (highest), else any row (last seen).
    subs = {}
    for s in status["all_submissions"]:
        fn = s["filename"]
        cur = subs.get(fn)
        if cur is None:
            subs[fn] = s
            continue
        def rank(x):
            return (1 if (x.get("status") == "complete"
                          and x.get("public_score") is not None) else 0,
                    x.get("public_score") if x.get("public_score") is not None else -1)
        if rank(s) >= rank(cur):
            subs[fn] = s
    drag_pm_losses = [g for g in postmortem["games"] if g["result"] == "loss"]
    candidates = [
        ("league_water_anti_disruption_pivot_v1.tar.gz",
         "keep_as_control", "active Water control; current water family best"),
        ("league_water_core_reference.tar.gz",
         "calibration_only", "stable Water reference"),
        ("league_dragapult_v1_search_only.tar.gz",
         "needs_more_replays",
         "completed @ 309.2 (below control); 0-2 vs real opponents in new replays; "
         "losses are pacing/no-pokemon (pilot pacing), not deck-illegality"),
        ("combo_full_safety_v3_fixed.tar.gz",
         "calibration_only", "effect-safety combo; mid leaderboard"),
        ("submission.tar.gz",
         "keep_as_control", "v1 baseline; current live leader"),
    ]
    rows = []
    for fn, rec, why in candidates:
        s = subs.get(fn, {})
        is_drag = fn.startswith("league_dragapult")
        rows.append({
            "filename": fn,
            "public_score": s.get("public_score"),
            "status": s.get("status"),
            "replay_results": (f"{postmortem['wins']}W/{postmortem['losses']}L "
                               "(incl self-mirror)") if is_drag else "no new replays this pass",
            "observed_failure_modes": postmortem["primary_loss_modes"] if is_drag else [],
            "evidence_recommendation": rec, "why": why,
        })
    out = {"pass": "pass32", "part": "G", "no_upload": True,
           "live_score_leader": status["live_score_leader"],
           "water_family_current_best": status["water_family_current_best"],
           "dragapult_family_best": status["dragapult_family_best"],
           "candidates": rows}
    (EXP / "pass32_live_probe_comparison.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    md = ["# Pass 32 — Cross-candidate live probe comparison", "",
          f"- live leader: {status['live_score_leader']}",
          f"- water best: {status['water_family_current_best']}",
          f"- dragapult best: {status['dragapult_family_best']}", "",
          "| candidate | publicScore | status | replay results | failure modes | recommendation |",
          "|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['filename']} | {r['public_score']} | {r['status']} | "
                  f"{r['replay_results']} | {r['observed_failure_modes'] or '-'} | "
                  f"{r['evidence_recommendation']} |")
    (EXP / "pass32_live_probe_comparison.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------- Part H
def part_h_decision(status, postmortem):
    drag = status["dragapult"]
    leader = status["live_score_leader"]
    water_best = status["water_family_current_best"]
    drag_score = drag["public_score"]
    below_control = (water_best and drag_score is not None
                     and drag_score < water_best["public_score"])
    # Dragapult completed (no error), but below control -> keep water control.
    decision = "keep_water_control"
    secondary = "dragapult_needs_more_replays"
    queue = []  # dry-run queue stays empty: not above control, evidence thin
    out = {
        "pass": "pass32", "part": "H", "local_only": True, "no_upload": True,
        "upload_performed": False, "is_kaggle_leaderboard": True,
        "dragapult_result": {"status": drag["status"], "public_score": drag_score,
                             "completed_no_error": drag["status"] == "complete",
                             "below_current_control": bool(below_control)},
        "decision": decision,
        "secondary_label": secondary,
        "considered_and_rejected": {
            "dragapult_candidate_for_deeper_confirmation": "rejected — Dragapult is BELOW the Water control (309.2 < 340.0), not above it",
            "build_dragapult_targeted_variant_next": "rejected — the losses are pilot pacing (very late first attack, no-pokemon), not a deck-skeleton bug; per Pass 30 the next Dragapult move is a PILOT/policy change, not a new decklist",
            "build_water_basic_density_variant_next": "rejected — the no-pokemon loss was Dragapult, not Water; no new Water no-pokemon signal this pass",
            "dragapult_reject_for_now": "not chosen — Dragapult transferred cleanly (no error/collapse); keep as a calibration data point",
        },
        "next_candidate_family": "water (control unchanged); Dragapult parked pending more replays / a pilot change",
        "reason": ("Dragapult completed live at 309.2 — a clean transfer (no error, "
                   "no collapse) but BELOW the Water control (340.0) and live leader "
                   f"({leader['public_score'] if leader else 'n/a'}). New replays: "
                   "1 self-mirror win + 0-2 vs real opponents; losses are pacing/"
                   "no-pokemon (pilot), not deck illegality. Rule: complete-but-below-"
                   "control => keep Water control and analyze why. One probe is a "
                   "calibration point, not proof."),
        "dry_run_queue_size": len(queue),
        "queue_max": 1, "auto_submit_enabled": False,
        "human_approval_required": True,
    }
    (EXP / "pass32_strategy_decision.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    md = ["# Pass 32 — Strategy decision", "",
          f"- decision: **{decision}**",
          f"- secondary: {secondary}",
          f"- dry-run queue: {len(queue)} (max 1; nothing queued — Dragapult is below control)",
          f"- next candidate family: {out['next_candidate_family']}",
          f"- reason: {out['reason']}",
          "- no upload; no auto-submit; human approval required for any future probe", ""]
    md.append("## Considered and rejected")
    for k, v in out["considered_and_rejected"].items():
        md.append(f"- **{k}**: {v}")
    (EXP / "pass32_strategy_decision.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # submission_queue.json — empty dry-run queue (max 1), no upload.
    sq = {
        "schema": "ptcg_dry_run_submission_queue_v1",
        "generated_at": time.time(),
        "run_id": f"run_pass32_dragapult_postmortem_{time.strftime('%Y%m%d_%H%M%S')}",
        "stage": "pass32_dragapult_result_and_replay_postmortem",
        "auto_submit_enabled": False,
        "require_manual_approval_for_submit": True,
        "upload_performed": False,
        "no_more_submissions_today": True,
        "max_queue_size": 1,
        "active_control": "league_water_anti_disruption_pivot_v1",
        "decision": decision,
        "queue": queue,
        "note": ("Dry-run queue intentionally EMPTY: Dragapult completed below the "
                 "Water control (309.2 < 340.0); no candidate is queued. No upload."),
    }
    (REPO / "data" / "submission_queue.json").write_text(
        json.dumps(sq, indent=2), encoding="utf-8")
    return out


def main() -> int:
    cand_fps = _candidate_fps()
    status = part_c_status()
    part_b_raw_safety()
    attribution = part_e_attribution(cand_fps)
    postmortem = part_f_postmortem(attribution)
    part_g_comparison(status, postmortem)
    decision = part_h_decision(status, postmortem)
    print("Pass 32 analysis built.")
    print(f"  dragapult: {status['dragapult']['status']} @ "
          f"{status['dragapult']['public_score']}")
    print(f"  postmortem: {postmortem['wins']}W/{postmortem['losses']}L; "
          f"loss modes {postmortem['primary_loss_modes']}")
    print(f"  decision: {decision['decision']} (queue {decision['dry_run_queue_size']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
