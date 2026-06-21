#!/usr/bin/env python3
"""PASS 44 — fast production health audit (read-only).

Identical hard/soft invariants to ``scripts/check_tournament_health.py --mode prod``
(it imports and reuses that module's ``run_checks`` / ``write_report`` verbatim), but
the per-file manifest sha-integrity reads are PREFETCHED CONCURRENTLY instead of
serially. The production snapshot now carries hundreds of game sidecars, and reading
each one sequentially over Object Storage exceeds the interactive tool boundary
(~2 min). Concurrent prefetch turns that into a few seconds while still hashing every
manifest-tracked object — so the audit stays complete, not sampled.

Read-only: lists + reads from prod Object Storage; never writes/pushes/leases/mutates.
Output (canonical, consumed by build_pass43_safety_preflight.py --reuse-health):
  data/experiments/pass43_tournament_health.json / .md
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import check_tournament_health as H  # noqa: E402
from ptcg_activegraph.tournament.storage import get_storage_backend  # noqa: E402

EXP = REPO / "data" / "experiments"


def _build_prod_bundle_concurrent(max_workers: int = 48) -> H.StateBundle:
    backend = get_storage_backend(env="production", backend="replit_app_storage")

    def _read(key: str):
        try:
            return backend.read_bytes(key) if backend.exists(key) else None
        except Exception:  # noqa: BLE001
            return None

    import json as _json
    raw = _read("events.jsonl")
    events = H.sync.parse_events_text(raw.decode("utf-8")) if raw else []
    mraw = _read("storage_manifest.json")
    manifest = _json.loads(mraw.decode("utf-8")) if mraw else {}
    games = [k for k in backend.list("games") if k.endswith(".json.gz")]
    qraw = _read("projections/scheduler_queue.json")
    queue = _json.loads(qraw.decode("utf-8")) if qraw else {}
    craw = _read("config.yaml")

    # Concurrently prefetch every manifest-tracked file's bytes into a cache so the
    # sha-integrity check (which reads each one) runs against memory, not the network.
    keys = [f.get("key") for f in (manifest.get("files") or []) if f.get("key")]
    cache: dict[str, bytes | None] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for key, data in zip(keys, ex.map(_read, keys)):
            cache[key] = data

    def cached_read(key: str):
        if key in cache:
            return cache[key]
        return _read(key)

    return H.StateBundle(
        "prod:" + backend.name, events, manifest, sorted(games), queue,
        craw.decode("utf-8") if craw else None, cached_read)


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    bundle = _build_prod_bundle_concurrent()
    res = H.run_checks(bundle, config_path_text=bundle.config_text)
    out_json = EXP / "pass43_tournament_health.json"
    out_md = EXP / "pass43_tournament_health.md"
    H.write_report(res, out_json, out_md, mode="prod", elapsed=time.time() - t0)
    healthy = not res.hard_failures
    print(f"pass44 prod health (concurrent): healthy={healthy} "
          f"hard_failures={[c.name for c in res.hard_failures]} "
          f"warnings={[c.name for c in res.warnings]} "
          f"sidecars={len(bundle.game_keys)} elapsed={round(time.time()-t0,1)}s")
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
