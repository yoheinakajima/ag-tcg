"""Pass 40 — public-reference benchmark lane (physically separate from our pool).

A self-contained lane for benchmarking OUR schedulable candidates against public
Kaggle reference agents (status :data:`external_reference`). **Zero leakage by
construction**:

* reference agents are NEVER written to ``candidate_pool.json`` and are NEVER
  emitted as ``TournamentParticipantRegistered`` (so :meth:`CandidatePool.from_events`
  never folds them — they never enter our pool, rankings, active-cap, or lifecycle);
* benchmark games use ``PublicBenchmark*`` event types that the normal
  :func:`projections.fold_games`, the scheduler, and the lifecycle manager never
  read (those read ``GameFinished`` only), so our rankings/queue/promotion/mutation
  lineage are untouched;
* every benchmark event is written to a SEPARATE ledger file
  (``data/tournament/benchmark/benchmark_events.jsonl``), not the main tournament
  ledger, and every event carries ``no_upload=true`` via :class:`TournamentLedger`.

Benchmark scores are *internal cg_typed-lane feasibility diagnostics only* — NOT our
rankings, NOT a Kaggle leaderboard, NOT a Kaggle score, and NOT a strength claim.
NO upload / submit / promote / mutate.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..graph.events import Event, EventType
from .ledger import TournamentLedger
from .pool import CandidatePool

REPO_ROOT = Path(__file__).resolve().parents[3]
REFERENCE_DIR = REPO_ROOT / "data" / "reference_agents"
DEFAULT_MANIFEST = REFERENCE_DIR / "reference_agent_manifest.json"
BENCHMARK_DIR = REPO_ROOT / "data" / "tournament" / "benchmark"
BENCHMARK_EVENTS_PATH = BENCHMARK_DIR / "benchmark_events.jsonl"
REFERENCE_POOL_PATH = BENCHMARK_DIR / "reference_pool.json"
PROJ_DIR = REPO_ROOT / "data" / "tournament" / "projections"

EXTERNAL_REFERENCE_STATUS = "external_reference"

_BENCH_CAVEAT = (
    "Internal cg_typed-lane benchmark feasibility only. These are NOT our rankings, "
    "NOT a Kaggle leaderboard, NOT a Kaggle score, and NOT a strength claim. "
    "Reference agents are benchmark opponents only — never in our candidate pool, "
    "submission queue, lifecycle, promotion, family-champion set, active-cap, or "
    "mutation lineage. NO upload / submit / promote / mutate."
)

# Canonical benchmark result codes (our candidate's perspective).
OUR_WIN = "our_win"
REFERENCE_WIN = "reference_win"
DRAW = "draw"
INVALID = "invalid"


# --------------------------------------------------------------------------- #
# opponents (derived from the Part F manifest; NEVER pool.Candidate objects)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BenchmarkOpponent:
    agent_id: str
    label: str
    deck_archetype: str
    status: str = EXTERNAL_REFERENCE_STATUS
    usage: str = "benchmark_opponent_only"
    tarball: str = ""
    tarball_sha256: str = ""
    content_sha256: str = ""
    optional: bool = False
    no_upload: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def load_opponents(manifest_path: str | Path | None = None,
                   include_optional: bool = True) -> list[BenchmarkOpponent]:
    """Load built reference agents from the Part F manifest as benchmark opponents.

    Only ``built`` entries are returned (a non-built optional agent is silently
    skipped). The result is sorted by ``agent_id`` for determinism.
    """
    p = Path(manifest_path) if manifest_path is not None else DEFAULT_MANIFEST
    raw = json.loads(p.read_text(encoding="utf-8"))
    out: list[BenchmarkOpponent] = []
    for a in raw.get("agents", []):
        if not a.get("built"):
            continue
        if a.get("optional") and not include_optional:
            continue
        out.append(BenchmarkOpponent(
            agent_id=a["agent_id"], label=a.get("label", a["agent_id"]),
            deck_archetype=a.get("deck_archetype", ""),
            status=a.get("pool_status", EXTERNAL_REFERENCE_STATUS),
            usage=a.get("usage", "benchmark_opponent_only"),
            tarball=a.get("tarball", ""), tarball_sha256=a.get("tarball_sha256", ""),
            content_sha256=a.get("content_sha256", ""),
            optional=bool(a.get("optional", False)),
        ))
    return sorted(out, key=lambda o: o.agent_id)


# --------------------------------------------------------------------------- #
# benchmark ledger (separate file)
# --------------------------------------------------------------------------- #
def benchmark_ledger(path: str | Path | None = None) -> TournamentLedger:
    """A no-upload ledger writing to the SEPARATE benchmark events file."""
    return TournamentLedger(path or BENCHMARK_EVENTS_PATH)


def registered_reference_ids(events: list[Event]) -> set[str]:
    rid: set[str] = set()
    for e in events:
        if e.event_type == EventType.PublicReferenceAgentRegistered.value:
            aid = e.payload.get("agent_id")
            if aid:
                rid.add(aid)
    return rid


def register_opponents(opponents: list[BenchmarkOpponent],
                       ledger: TournamentLedger | None = None) -> dict:
    """Idempotently register reference agents into the benchmark lane.

    Emits one ``PublicReferenceAgentRegistered`` per not-yet-registered opponent on
    the benchmark ledger and refreshes the ``reference_pool.json`` snapshot. This is
    the ONLY registration path for references; it never touches the main pool or the
    main ledger.
    """
    led = ledger or benchmark_ledger()
    already = registered_reference_ids(led.load())
    newly: list[str] = []
    for o in opponents:
        if o.agent_id in already:
            continue
        led.emit(EventType.PublicReferenceAgentRegistered, {
            "agent_id": o.agent_id, "label": o.label,
            "status": o.status, "usage": o.usage,
            "deck_archetype": o.deck_archetype,
            "tarball": o.tarball, "tarball_sha256": o.tarball_sha256,
            "content_sha256": o.content_sha256, "optional": o.optional,
            "guardrails": [
                "benchmark opponent only; never our candidate",
                "never in pool / queue / promotion / lifecycle / mutation lineage",
                "never counted toward active-cap or 'our best' rankings",
                "never uploaded / submitted / auto-submitted",
            ],
        }, tags=["pass40", "benchmark", "external_reference"])
        newly.append(o.agent_id)

    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "schema": "pass40_reference_pool_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "no_upload": True, "usage": "benchmark_opponent_only",
        "status": EXTERNAL_REFERENCE_STATUS, "caveat": _BENCH_CAVEAT,
        "note": "Separate from candidate_pool.json. These are NOT our candidates.",
        "opponents": [o.to_dict() for o in sorted(opponents, key=lambda x: x.agent_id)],
    }
    REFERENCE_POOL_PATH.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return {
        "registered_total": len(opponents),
        "newly_registered": newly,
        "already_registered": sorted(already),
        "reference_pool_path": str(REFERENCE_POOL_PATH),
        "benchmark_events_path": str(BENCHMARK_EVENTS_PATH),
        "no_upload": True,
    }


# --------------------------------------------------------------------------- #
# benchmark scheduling (our schedulable candidates x reference opponents)
# --------------------------------------------------------------------------- #
@dataclass
class BenchmarkGame:
    game_id: str
    our_candidate: str
    reference_id: str
    our_seat: int          # 0 or 1 (the reference takes the other seat)
    reason: str = "public_benchmark"

    def to_dict(self) -> dict:
        return asdict(self)


def _directed_key(our: str, ref: str, our_seat: int) -> str:
    return f"{our}~{ref}@{our_seat}"


def build_benchmark_state(events: list[Event]) -> dict[str, int]:
    """Directed seat counts ``our~ref@seat -> n`` folded from finished bench games."""
    counts: dict[str, int] = {}
    for e in events:
        if e.event_type != EventType.PublicBenchmarkGameFinished.value:
            continue
        our = e.payload.get("our_candidate")
        ref = e.payload.get("reference_id")
        seat = e.payload.get("our_seat")
        if our and ref and seat in (0, 1):
            k = _directed_key(our, ref, int(seat))
            counts[k] = counts.get(k, 0) + 1
    return counts


def build_benchmark_worklist(our_candidate_ids: list[str],
                             opponents: list[BenchmarkOpponent],
                             events: list[Event],
                             max_games: int) -> list[BenchmarkGame]:
    """Deterministic, bounded benchmark worklist: each OUR candidate vs each ref.

    Pairs are emitted least-played-first, and each pair contributes BOTH seats
    before the worklist expands to the next pair, so any even-sized cap (e.g. a
    truncated worklist) stays seat-balanced. This is completely independent of the
    normal scheduler (which only pairs schedulable candidates with one another).
    """
    counts = build_benchmark_state(events)
    pairs = sorted(
        ((our, o.agent_id) for our in sorted(set(our_candidate_ids))
         for o in opponents),
        key=lambda pr: pr,
    )

    def pair_games(our: str, ref: str) -> int:
        return (counts.get(_directed_key(our, ref, 0), 0)
                + counts.get(_directed_key(our, ref, 1), 0))

    games: list[BenchmarkGame] = []
    seq = dict(counts)
    while len(games) < max_games and pairs:
        progressed = False
        for our, ref in sorted(pairs, key=lambda pr: (pair_games(*pr), pr)):
            if len(games) >= max_games:
                break
            # Emit BOTH seats for this pair before expanding to more pairs, so any
            # even-sized cap (e.g. a truncated worklist) stays seat-balanced.
            for _ in range(2):
                if len(games) >= max_games:
                    break
                n0 = seq.get(_directed_key(our, ref, 0), 0)
                n1 = seq.get(_directed_key(our, ref, 1), 0)
                our_seat = 0 if n0 <= n1 else 1
                n = seq.get(_directed_key(our, ref, our_seat), 0)
                gid = f"bench|{our}~{ref}@{our_seat}|g{n}"
                games.append(BenchmarkGame(gid, our, ref, our_seat))
                seq[_directed_key(our, ref, our_seat)] = n + 1
                counts[_directed_key(our, ref, our_seat)] = n + 1
                progressed = True
        if not progressed:
            break
    return games


def finished_benchmark_game_ids(events: list[Event]) -> set[str]:
    out: set[str] = set()
    for e in events:
        if e.event_type == EventType.PublicBenchmarkGameFinished.value:
            gid = e.payload.get("game_id")
            if gid:
                out.add(str(gid))
    return out


def classify_result(game_result: dict) -> str:
    """Map a ``run_one_game_subprocess`` result (reference is the 'cand') to our code.

    The reference agent is always passed as the subprocess 'candidate' (its dir holds
    the bundled ``cg/`` the child chdirs into), so ``candidate_won`` is the
    REFERENCE's outcome and must be inverted for our perspective.
    """
    if not game_result.get("completed") or game_result.get("error") \
            or game_result.get("timeout"):
        return INVALID
    if game_result.get("draw"):
        return DRAW
    ref_won = game_result.get("candidate_won")
    if ref_won is True:
        return REFERENCE_WIN
    if ref_won is False:
        return OUR_WIN
    return DRAW


# --------------------------------------------------------------------------- #
# folding + projection (benchmark-only; separate from our rankings)
# --------------------------------------------------------------------------- #
def fold_benchmark_games(events: list[Event]) -> dict:
    """Aggregate PublicBenchmarkGameFinished into per-pair and per-candidate stats."""
    per_pair: dict[str, dict] = {}
    per_our: dict[str, dict] = {}
    totals = {"games": 0, OUR_WIN: 0, REFERENCE_WIN: 0, DRAW: 0, INVALID: 0}

    def pslot(d: dict, key: str, **extra) -> dict:
        return d.setdefault(key, {"games": 0, OUR_WIN: 0, REFERENCE_WIN: 0,
                                  DRAW: 0, INVALID: 0, **extra})

    for e in events:
        if e.event_type != EventType.PublicBenchmarkGameFinished.value:
            continue
        our = e.payload.get("our_candidate")
        ref = e.payload.get("reference_id")
        res = e.payload.get("result")
        if not our or not ref or res not in (OUR_WIN, REFERENCE_WIN, DRAW, INVALID):
            continue
        totals["games"] += 1
        totals[res] += 1
        pk = f"{our}~{ref}"
        pp = pslot(per_pair, pk, our_candidate=our, reference_id=ref)
        pp["games"] += 1
        pp[res] += 1
        po = pslot(per_our, our)
        po["games"] += 1
        po[res] += 1
    return {"per_pair": per_pair, "per_our": per_our, "totals": totals}


def write_benchmark_projection(events: list[Event],
                               opponents: list[BenchmarkOpponent] | None = None
                               ) -> dict:
    """Write ``benchmark_results.{json,md}`` (clearly labelled benchmark-only)."""
    PROJ_DIR.mkdir(parents=True, exist_ok=True)
    agg = fold_benchmark_games(events)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    opp_labels = {o.agent_id: o.label for o in (opponents or [])}

    def decisive_rate(s: dict) -> float | None:
        dec = s[OUR_WIN] + s[REFERENCE_WIN]
        return round(s[OUR_WIN] / dec, 4) if dec else None

    pairs = []
    for pk in sorted(agg["per_pair"]):
        s = agg["per_pair"][pk]
        pairs.append({
            "our_candidate": s["our_candidate"], "reference_id": s["reference_id"],
            "reference_label": opp_labels.get(s["reference_id"], s["reference_id"]),
            "games": s["games"], "our_wins": s[OUR_WIN],
            "reference_wins": s[REFERENCE_WIN], "draws": s[DRAW],
            "invalid": s[INVALID], "our_decisive_win_rate": decisive_rate(s),
        })
    per_our = []
    for cid in sorted(agg["per_our"]):
        s = agg["per_our"][cid]
        per_our.append({
            "our_candidate": cid, "games": s["games"], "our_wins": s[OUR_WIN],
            "reference_wins": s[REFERENCE_WIN], "draws": s[DRAW],
            "invalid": s[INVALID], "our_decisive_win_rate": decisive_rate(s),
        })

    payload = {
        "schema": "pass40_benchmark_results_v1", "generated_at": now,
        "no_upload": True, "caveat": _BENCH_CAVEAT, "totals": agg["totals"],
        "by_pair": pairs, "by_our_candidate": per_our,
    }
    (PROJ_DIR / "benchmark_results.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    lines = ["# Public-Reference Benchmark Results (benchmark-only)", "",
             f"_{_BENCH_CAVEAT}_", "", f"- generated: {now}",
             f"- totals: {agg['totals']}", "",
             "## Our candidate vs each public reference", "",
             "| our_candidate | reference | games | our_W | ref_W | draw | invalid "
             "| our_decisive_wr |", "|---|---|---|---|---|---|---|---|"]
    for p in pairs:
        wr = "—" if p["our_decisive_win_rate"] is None else f"{p['our_decisive_win_rate']:.3f}"
        lines.append(
            f"| {p['our_candidate']} | {p['reference_label']} | {p['games']} "
            f"| {p['our_wins']} | {p['reference_wins']} | {p['draws']} "
            f"| {p['invalid']} | {wr} |")
    lines += ["", "## Our candidate totals (across references)", "",
              "| our_candidate | games | our_W | ref_W | draw | invalid | our_decisive_wr |",
              "|---|---|---|---|---|---|---|"]
    for p in per_our:
        wr = "—" if p["our_decisive_win_rate"] is None else f"{p['our_decisive_win_rate']:.3f}"
        lines.append(
            f"| {p['our_candidate']} | {p['games']} | {p['our_wins']} "
            f"| {p['reference_wins']} | {p['draws']} | {p['invalid']} | {wr} |")
    (PROJ_DIR / "benchmark_results.md").write_text("\n".join(lines) + "\n",
                                                   encoding="utf-8")
    return {"per_pair": pairs, "per_our": per_our, "totals": agg["totals"],
            "json": str(PROJ_DIR / "benchmark_results.json"),
            "md": str(PROJ_DIR / "benchmark_results.md")}


# --------------------------------------------------------------------------- #
# zero-leakage assertions (used by the integration artifact + tests)
# --------------------------------------------------------------------------- #
def assert_zero_leakage(pool: CandidatePool, main_events: list[Event],
                        opponents: list[BenchmarkOpponent]) -> dict:
    """Return a structured proof that references never entered our pool/ledger.

    Checks (all must be True):
      * no reference agent_id appears as a pool candidate;
      * no reference status appears among pool candidates;
      * the MAIN ledger emits no PublicBenchmark*/PublicReferenceAgentRegistered
        events and no TournamentParticipantRegistered for any reference id;
      * no reference id appears in any main GameFinished game.
    """
    ref_ids = {o.agent_id for o in opponents}
    pool_ids = {c.candidate_id for c in pool.candidates}
    pool_statuses = {c.status for c in pool.candidates}

    bench_types = {
        EventType.PublicReferenceAgentRegistered.value,
        EventType.PublicBenchmarkTickStarted.value,
        EventType.PublicBenchmarkGameScheduled.value,
        EventType.PublicBenchmarkGameStarted.value,
        EventType.PublicBenchmarkGameFinished.value,
        EventType.PublicBenchmarkProjectionUpdated.value,
        EventType.PublicBenchmarkTickFinished.value,
    }
    main_bench_events = [e for e in main_events if e.event_type in bench_types]
    reg_ref = [e for e in main_events
               if e.event_type == EventType.TournamentParticipantRegistered.value
               and (e.payload.get("candidate_id") in ref_ids)]
    gf_ref = []
    for e in main_events:
        if e.event_type != EventType.GameFinished.value:
            continue
        if e.payload.get("candidate_a") in ref_ids or e.payload.get("candidate_b") in ref_ids:
            gf_ref.append(e.payload.get("game_id"))

    checks = {
        "no_reference_in_pool_ids": not (ref_ids & pool_ids),
        "no_external_reference_status_in_pool":
            EXTERNAL_REFERENCE_STATUS not in pool_statuses,
        "no_benchmark_events_in_main_ledger": len(main_bench_events) == 0,
        "no_reference_participant_registered_in_main": len(reg_ref) == 0,
        "no_reference_in_main_finished_games": len(gf_ref) == 0,
    }
    return {"zero_leakage": all(checks.values()), "checks": checks,
            "reference_ids": sorted(ref_ids),
            "pool_candidate_count": len(pool_ids)}
