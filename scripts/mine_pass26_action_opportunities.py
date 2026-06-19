#!/usr/bin/env python3
"""Pass 26 (Part D) — replay action-opportunity miner.

LOCAL / READ-ONLY. For every Water-family replay (our Kyogre/Abomasnow deck
present), identify our seat from the replay registry and iterate EVERY decision
where our agent actually acted (``observation.current.yourIndex == our_seat`` and
a non-empty ``select.option`` list). For each decision we capture the raw select
metadata, resolve every legal option to a card id/name + action class where the
log permits, summarise our board / the opponent board, tag hazards, and assign
the decision to a known strategic seam.

Hard honesty rules (from spec Part D):
  * Do NOT infer card effects beyond the logs / local card DB.
  * If an option cannot be resolved to a card or action class, mark it ``unknown``.
  * Mega Abomasnow ex (723) is a Stage-1 evolution payoff, NEVER a Basic.
  * Face-down opponent cards (prizes, deck) are NEVER treated as known.

Outputs (data/experiments/):
  * pass26_action_opportunities.json   — full structured corpus + aggregates
  * pass26_action_opportunities.md     — human summary
  * pass26_action_opportunities.jsonl  — one decision per line (feeds Parts E/F)

No upload, no submission, no root edits.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "meta_replays" / "raw"
REGISTRY = REPO / "data" / "meta_replays" / "replay_registry.json"
CARD_DB = REPO / "data" / "cards" / "EN_Card_Data.csv"
PLAYBOOK = REPO / "playbooks" / "pass25_water_hardening.yaml"

OUT_JSON = REPO / "data" / "experiments" / "pass26_action_opportunities.json"
OUT_MD = REPO / "data" / "experiments" / "pass26_action_opportunities.md"
OUT_JSONL = REPO / "data" / "experiments" / "pass26_action_opportunities.jsonl"

# Numeric select.context codes -> stable string labels (verified against the
# real replay corpus). Anything unseen falls through to ctx<N>.
CTX_LABELS = {
    0: "main", 1: "setup_active", 2: "setup_bench", 3: "setup_other",
    4: "setup_confirm", 7: "search_to_hand", 8: "discard", 22: "ctx22",
    38: "draw_count", 41: "yesno_isfirst",
}

OUR_DECK_CARDS = {721, 722, 723}  # Kyogre / Snover / Mega Abomasnow ex


def _load_card_db():
    """id -> {'name','type_line'} from the local EN card DB (gitignored)."""
    db = {}
    if not CARD_DB.exists():
        return db
    with CARD_DB.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                cid = int(row["Card ID"])
            except (TypeError, ValueError):
                continue
            db[cid] = {
                "name": row.get("Card Name"),
                "type_line": row.get("Stage (Pokémon)/Type (Energy and Trainer)"),
            }
    return db


def _load_roles():
    """Parse the role -> [card ids] map from the Water playbook (no yaml dep)."""
    roles = {}
    if not PLAYBOOK.exists():
        return roles
    in_roles = False
    for line in PLAYBOOK.read_text(encoding="utf-8").splitlines():
        if line.startswith("roles:"):
            in_roles = True
            continue
        if in_roles:
            if line and not line.startswith((" ", "\t")):
                break
            s = line.strip()
            if not s or ":" not in s:
                continue
            key, val = s.split(":", 1)
            ids = []
            val = val.strip().strip("[]")
            for tok in val.split(","):
                tok = tok.strip()
                if tok.isdigit():
                    ids.append(int(tok))
            roles[key.strip()] = ids
    return roles


def _role_of(cid, roles):
    for role, ids in roles.items():
        if cid in ids:
            return role
    return None


def _class_from_type_line(tl):
    """Map a card DB type line to a play action class."""
    if not tl:
        return None
    t = tl.lower()
    if "energy" in t:
        return "attach"
    if t == "item" or "item" in t:
        return "play_trainer"
    if "supporter" in t:
        return "play_supporter"
    if "stadium" in t:
        return "play_stadium"
    if "tool" in t:
        return "play_tool"
    if "stage" in t:          # Stage 1 / Stage 2 -> evolution
        return "evolve"
    if "basic pok" in t:
        return "play_basic"
    return None


def _card_at(zone, idx):
    if isinstance(zone, list) and isinstance(idx, int) and 0 <= idx < len(zone):
        c = zone[idx]
        if isinstance(c, dict):
            return c.get("id")
    return None


def _resolve_option(o, board, ctx, db):
    """Resolve a single legal option to (card_id, card_name, action_class).

    Verified raw schema (real corpus):
      * ``attackId`` present       -> attack (attacker = our active)
      * ``type`` == 14, no index   -> end turn
      * ``type`` == 8              -> attach energy (card = our hand[index])
      * ``type`` == 7 / 3          -> play / select card  (card = our hand[index])
      * ``index`` is the position WITHIN the option's zone: area 2 (or absent on
        a Main play option) = our hand; area 1 = our deck (HIDDEN -> unresolved).

    Only resolves cards the log actually exposes (our hand / our active). The
    deck is hidden, so ctx7 search TARGETS stay unresolved (card_id=None) -- an
    honest limitation, not a guess.
    """
    out = {
        "index": o.get("index"), "type": o.get("type"),
        "area": o.get("area"), "inPlayArea": o.get("inPlayArea"),
        "inPlayIndex": o.get("inPlayIndex"), "playerIndex": o.get("playerIndex"),
        "card_id": None, "card_name": None, "role": None,
        "action_class": "unknown",
    }
    otype = o.get("type")
    area = o.get("area")
    idx = o.get("index")

    # Attacks are self-identifying via attackId; attacker is our active.
    if o.get("attackId") is not None:
        out["attack_id"] = o.get("attackId")
        active = board.get("active") or []
        cid = active[0].get("id") if active and isinstance(active[0], dict) else None
        out["card_id"] = cid
        out["action_class"] = "attack"
    elif otype == 14:
        out["action_class"] = "end"
    else:
        # Resolve the referenced card from our hand when the zone is the hand
        # (area 2, or a Main play option that omits area). area 1 = deck (hidden).
        cid = None
        if area in (2, None):
            cid = _card_at(board.get("hand"), idx)
        out["card_id"] = cid
        type_line = db.get(cid, {}).get("type_line") if cid is not None else None

        if ctx == 7:
            ac = "search_to_hand"
        elif ctx == 8:
            ac = "discard"
        elif ctx == 38:
            ac = "draw_count"
        elif ctx == 41:
            ac = "unknown"                       # binary yes/no, no card
        else:                                    # Main / setup play options
            ac = _class_from_type_line(type_line)
            if ac is None and otype == 8:
                ac = "attach"                    # energy attach (card unresolved)
            if ac is None:
                ac = "unknown"
        out["action_class"] = ac

    cid = out["card_id"]
    if cid is not None:
        meta = db.get(cid, {})
        out["card_name"] = meta.get("name") or f"card_{cid}"
        out["role"] = _role_of(cid, ROLES)
        # Hard guard: 723 (Mega Abomasnow ex) is a Stage-1 evolution, never Basic.
        if cid == 723 and out["action_class"] == "play_basic":
            out["action_class"] = "evolve"
    return out


def _zone_cards(zone, db):
    names = []
    if isinstance(zone, list):
        for c in zone:
            if isinstance(c, dict):
                cid = c.get("id")
                names.append({"id": cid,
                              "name": db.get(cid, {}).get("name") if cid else None})
    return names


def _board_state(player, db):
    active = player.get("active") or []
    active_card = None
    if active and isinstance(active[0], dict):
        aid = active[0].get("id")
        active_card = {"id": aid, "name": db.get(aid, {}).get("name") if aid else None}
    bench = _zone_cards(player.get("bench"), db)
    return {
        "active": active_card,
        "bench": bench,
        "bench_count": len(bench),
        "pokemon_count": (1 if active_card else 0) + len(bench),
        "hand": _zone_cards(player.get("hand"), db),
        "hand_count": player.get("handCount", len(player.get("hand") or [])),
        "deck_count": player.get("deckCount"),
        "discard": _zone_cards(player.get("discard"), db),
        "prize_remaining": len(player.get("prize") or [])
        if isinstance(player.get("prize"), list) else player.get("prize"),
        "status": {k: player.get(k) for k in
                   ("asleep", "burned", "confused", "paralyzed", "poisoned")
                   if player.get(k)},
    }


def _opp_summary(player, db):
    if not isinstance(player, dict):
        return None
    active = player.get("active") or []
    active_card = None
    if active and isinstance(active[0], dict):
        aid = active[0].get("id")
        active_card = {"id": aid, "name": db.get(aid, {}).get("name") if aid else None}
    return {
        "active": active_card,
        "bench_count": len(player.get("bench") or []),
        "hand_count": player.get("handCount"),
        "deck_count": player.get("deckCount"),
        "prize_remaining": len(player.get("prize") or [])
        if isinstance(player.get("prize"), list) else player.get("prize"),
    }


def _hazards(board, opp, opp_arch, perspective):
    tags = []
    dc = board.get("deck_count")
    if isinstance(dc, int):
        if dc <= 8:
            tags.append("low_deck")
        if dc <= 4:
            tags.append("very_low_deck")
    if board.get("bench_count") == 0:
        tags.append("bench_empty")
    if board.get("pokemon_count") <= 1:
        tags.append("board_thin")
    active = board.get("active") or {}
    if active and board.get("bench_count") == 0:
        tags.append("active_alone")
    # Prize state (face-up counts only; never reads face-down identities).
    pr = board.get("prize_remaining")
    opr = opp.get("prize_remaining") if isinstance(opp, dict) else None
    if isinstance(pr, int) and isinstance(opr, int):
        if pr > opr:
            tags.append("behind_on_prizes")
        if opr <= 2:
            tags.append("prize_pressure")
    if perspective == "self_mirror" or (opp_arch and "mirror" in opp_arch):
        tags.append("mirror_grind")
    if opp_arch and ("psychic" in opp_arch or "positive_control" in opp_arch):
        tags.append("positive_control_pressure")
    return tags


def _seam(tags, opp_arch, perspective):
    if "mirror_grind" in tags and ("low_deck" in tags or "very_low_deck" in tags):
        return "mirror_deckout"
    if "board_thin" in tags or "active_alone" in tags:
        return "no_pokemon_loss"
    if opp_arch and ("psychic" in opp_arch or "positive_control" in opp_arch):
        return "psychic_positive_control"
    if opp_arch and ("metal" in opp_arch or "fighting" in opp_arch
                     or "zacian" in opp_arch):
        return "fighting_tempo"
    return "unknown"


def _attribution(deck_label):
    dl = (deck_label or "").lower()
    if "pivot" in dl or "anti_disruption" in dl:
        return "league_water_anti_disruption_pivot_v1"
    if "core" in dl or "reference" in dl:
        return "league_water_core_reference"
    if "mirror" in dl:
        return "mirror_or_old_deck"
    if dl:
        return f"other:{deck_label}"
    return "unknown"


ROLES = {}


def main() -> int:
    global ROLES
    db = _load_card_db()
    ROLES = _load_roles()
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))

    decisions = []
    per_episode = []
    ctx_counter = {}
    action_class_counter = {}
    seam_counter = {}
    hazard_counter = {}
    total_options = 0
    unresolved_options = 0
    selection_recorded = 0

    for rec in reg.get("records", []):
        seats = rec.get("seats") or []
        archs = [(s.get("archetype") or {}).get("archetype_id") for s in seats]
        if not any(a and "water_kyogre" in a for a in archs):
            continue  # not a Water-family episode
        eid = str(rec.get("episode_id"))
        seat = rec.get("our_seat")
        fn = rec.get("filename")
        raw_path = RAW / (fn or f"{eid}.json")
        if not raw_path.exists():
            per_episode.append({"episode_id": eid, "raw_present": False})
            continue
        our_seat_obj = seats[seat] if isinstance(seat, int) and seat < len(seats) else {}
        deck_label = our_seat_obj.get("deck_label")
        attribution = _attribution(deck_label)
        opp_arch = None
        for s in seats:
            if not s.get("is_ours"):
                opp_arch = (s.get("archetype") or {}).get("archetype_id")
        perspective = rec.get("perspective")
        rew = rec.get("our_reward")
        rew = rew if isinstance(rew, (int, float)) else 0
        result = ("win" if rew > 0 else "loss" if rew < 0 else "draw")
        if perspective == "self_mirror":
            result = "mirror"

        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        ep_decisions = 0
        ep_ctx = {}
        for s_idx, step in enumerate(raw.get("steps", [])):
            if not isinstance(step, list):
                continue
            for obs_rec in step:
                if not isinstance(obs_rec, dict):
                    continue
                obs = obs_rec.get("observation")
                if not isinstance(obs, dict):
                    continue
                cur = obs.get("current") or {}
                if cur.get("yourIndex") != seat:
                    continue
                sel = obs.get("select")
                if not isinstance(sel, dict):
                    continue
                opts = sel.get("option") or []
                if not opts:
                    continue
                ctx = sel.get("context")
                ctx_label = CTX_LABELS.get(ctx, f"ctx{ctx}")
                players = cur.get("players") or []
                me = players[seat] if seat < len(players) else {}
                opp = players[1 - seat] if len(players) > 1 else None
                board = _board_state(me, db)
                opp_sum = _opp_summary(opp, db)
                hazards = _hazards(board, opp_sum or {}, opp_arch, perspective)
                seam = _seam(hazards, opp_arch, perspective)

                resolved = []
                for o in opts:
                    if not isinstance(o, dict):
                        resolved.append({"action_class": "unknown", "card_id": None})
                        unresolved_options += 1
                        total_options += 1
                        continue
                    r = _resolve_option(o, me, ctx, db)
                    resolved.append(r)
                    total_options += 1
                    if r["action_class"] == "unknown" and r["card_id"] is None:
                        unresolved_options += 1

                selected = obs_rec.get("action")
                sel_idx = [i for i in (selected or [])
                           if isinstance(i, int) and not isinstance(i, bool)
                           and 0 <= i < len(resolved)]
                if selected:
                    selection_recorded += 1
                selected_classes = sorted({resolved[i]["action_class"]
                                           for i in sel_idx})
                selected_cards = sorted({resolved[i]["card_name"]
                                         for i in sel_idx
                                         if resolved[i].get("card_name")})
                available_classes = sorted({r["action_class"] for r in resolved})

                d = {
                    "episode_id": eid,
                    "step": s_idx,
                    "turn": cur.get("turn"),
                    "our_seat": seat,
                    "attribution": attribution,
                    "deck_label": deck_label,
                    "opponent_archetype": opp_arch,
                    "perspective": perspective,
                    "result": result,
                    "context": ctx,
                    "context_label": ctx_label,
                    "select_type": sel.get("type"),
                    "min_count": sel.get("minCount"),
                    "max_count": sel.get("maxCount"),
                    "forced": (isinstance(sel.get("minCount"), int)
                               and sel.get("minCount") == sel.get("maxCount")
                               and (sel.get("minCount") or 0) > 0
                               and len(opts) <= (sel.get("minCount") or 0)),
                    "num_options": len(opts),
                    "selected_indices": selected,
                    "selected_action_classes": selected_classes,
                    "selected_cards": selected_cards,
                    "available_action_classes": available_classes,
                    "legal_options": resolved,
                    "board": board,
                    "opponent": opp_sum,
                    "hazards": hazards,
                    "seam": seam,
                }
                decisions.append(d)
                ep_decisions += 1
                ep_ctx[ctx_label] = ep_ctx.get(ctx_label, 0) + 1
                ctx_counter[ctx_label] = ctx_counter.get(ctx_label, 0) + 1
                for ac in available_classes:
                    action_class_counter[ac] = action_class_counter.get(ac, 0) + 1
                seam_counter[seam] = seam_counter.get(seam, 0) + 1
                for h in hazards:
                    hazard_counter[h] = hazard_counter.get(h, 0) + 1

        per_episode.append({
            "episode_id": eid, "raw_present": True, "our_seat": seat,
            "attribution": attribution, "deck_label": deck_label,
            "opponent_archetype": opp_arch, "perspective": perspective,
            "result": result, "decisions": ep_decisions,
            "by_context": dict(sorted(ep_ctx.items())),
        })

    resolved_class_options = total_options - unresolved_options
    summary = {
        "pass": "26", "part": "D", "local_only": True, "no_upload": True,
        "upload_performed": False,
        "note": ("Replay action-opportunity mining over real Water-family games. "
                 "Cards are resolved ONLY from our own visible zones; the deck is "
                 "hidden so ctx7 search targets stay unresolved by design. Mega "
                 "Abomasnow ex (723) is always classed as an evolution, never a "
                 "Basic."),
        "episodes_analyzed": sum(1 for e in per_episode if e.get("raw_present")),
        "decisions_mined": len(decisions),
        "contexts_covered": dict(sorted(ctx_counter.items(),
                                         key=lambda kv: -kv[1])),
        "action_class_distribution": dict(sorted(action_class_counter.items(),
                                                 key=lambda kv: -kv[1])),
        "seam_distribution": dict(sorted(seam_counter.items(),
                                         key=lambda kv: -kv[1])),
        "hazard_distribution": dict(sorted(hazard_counter.items(),
                                           key=lambda kv: -kv[1])),
        "total_legal_options": total_options,
        "resolved_options": resolved_class_options,
        "unresolved_options": unresolved_options,
        "unresolved_option_rate": round(unresolved_options / total_options, 4)
        if total_options else 0.0,
        "decisions_with_recorded_selection": selection_recorded,
        "per_episode": per_episode,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with OUT_JSONL.open("w", encoding="utf-8") as f:
        for d in decisions:
            f.write(json.dumps(d) + "\n")

    L = ["# Pass 26 — Replay Action Opportunities (Part D)", "",
         "> LOCAL / READ-ONLY. Every decision our seat actually faced across the "
         "Water-family replays, with each legal option resolved to a card + action "
         "class where the log permits. The deck is hidden, so ctx7 search targets "
         "are intentionally unresolved. Mega Abomasnow ex is never a Basic.", "",
         f"- episodes analyzed: **{summary['episodes_analyzed']}**",
         f"- decisions mined: **{summary['decisions_mined']}**",
         f"- legal options: {summary['total_legal_options']} "
         f"(resolved {summary['resolved_options']}, unresolved "
         f"{summary['unresolved_options']}, unresolved rate "
         f"**{summary['unresolved_option_rate']}**)",
         f"- decisions with a recorded selection: "
         f"{summary['decisions_with_recorded_selection']}", "",
         "## Contexts covered", "", "| context | decisions |", "|---|---|"]
    for k, v in summary["contexts_covered"].items():
        L.append(f"| {k} | {v} |")
    L += ["", "## Action classes available (option-level)", "",
          "| action class | options |", "|---|---|"]
    for k, v in summary["action_class_distribution"].items():
        L.append(f"| {k} | {v} |")
    L += ["", "## Seam distribution", "", "| seam | decisions |", "|---|---|"]
    for k, v in summary["seam_distribution"].items():
        L.append(f"| {k} | {v} |")
    L += ["", "## Hazard tags", "", "| hazard | decisions |", "|---|---|"]
    for k, v in summary["hazard_distribution"].items():
        L.append(f"| {k} | {v} |")
    L += ["", "## Per-episode", "",
          "| episode | attribution | opp | result | decisions | contexts |",
          "|---|---|---|---|---|---|"]
    for e in per_episode:
        if not e.get("raw_present"):
            L.append(f"| {e['episode_id']} | (raw absent) | — | — | — | — |")
            continue
        L.append(f"| {e['episode_id']} | {e['attribution']} | "
                 f"{e['opponent_archetype']} | {e['result']} | {e['decisions']} | "
                 f"{e['by_context']} |")
    L += ["", f"_{summary['note']}_", ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    print(f"episodes={summary['episodes_analyzed']} decisions={summary['decisions_mined']} "
          f"options={total_options} unresolved_rate={summary['unresolved_option_rate']}")
    print("contexts:", summary["contexts_covered"])
    print("action_classes:", summary["action_class_distribution"])
    print("seams:", summary["seam_distribution"])
    print(f"-> {OUT_JSONL.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
