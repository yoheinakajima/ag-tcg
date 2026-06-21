#!/usr/bin/env python3
"""Pass 40 (Part K, OPTIONAL) — cg Search API import / one-step feasibility smoke.

Confirms the bundled cg SDK exposes a usable *search* API surface
(``search_begin/step/end/release``) and that the native ``libcg.so`` loads and serves
card/attack data — establishing whether a typed search-based gameplay seam is FEASIBLE
for future exploration. It does NOT run any search, MCTS, or torch, and it generates NO
candidate. Each import runs in a hard-timeout subprocess (native lib must never hang
the parent). Outputs:
  data/experiments/pass40_search_api_feasibility.{json,md}
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"
REF = REPO / "data" / "reference_agents"
EXTRACTED = REF / "tarballs" / "_extracted"
CHILD = REPO / "src/ptcg_activegraph/experiments/_cg_search_api_smoke_child.py"

from ptcg_activegraph.tournament import benchmark as B  # noqa: E402
from ptcg_activegraph.tournament.artifacts import safe_extract_all  # noqa: E402

TIMEOUT = 60
N_AGENTS = 2  # a representative subset is sufficient for a feasibility smoke


def _ensure_extracted(agent_id: str) -> Path:
    import tarfile
    run = EXTRACTED / agent_id
    if not (run / "cg" / "libcg.so").is_file():
        run.mkdir(parents=True, exist_ok=True)
        with tarfile.open(REF / "tarballs" / f"{agent_id}.tar.gz") as t:
            safe_extract_all(t, run)
    return run


def _smoke(agent_id: str) -> dict:
    run = _ensure_extracted(agent_id)
    try:
        proc = subprocess.run(
            [sys.executable, str(CHILD), str(run)],
            capture_output=True, text=True, timeout=TIMEOUT)
        if proc.returncode != 0:
            return {"agent_id": agent_id, "ok": False,
                    "error": f"rc={proc.returncode}: {proc.stderr[-300:]}"}
        last = [l for l in proc.stdout.strip().splitlines() if l.strip()][-1]
        res = json.loads(last)
        res["agent_id"] = agent_id
        return res
    except subprocess.TimeoutExpired:
        return {"agent_id": agent_id, "ok": False, "error": "timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"agent_id": agent_id, "ok": False,
                "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    opponents = B.load_opponents(include_optional=False)[:N_AGENTS]
    results = [_smoke(o.agent_id) for o in opponents]

    feasible = bool(results) and all(r.get("ok") for r in results)
    search_api_ok = bool(results) and all(r.get("search_api_complete") for r in results)
    payload = {
        "schema": "pass40_search_api_feasibility_v1", "pass": "40", "part": "K",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "optional": True, "no_upload": True, "upload_performed": False,
        "auto_submit": False, "github_push": False, "candidate_generation": False,
        "no_mcts": True, "no_torch": True,
        "note": ("Import + one-step data smoke only. Confirms the cg search API surface "
                 "(search_begin/step/end/release) exists and libcg.so loads/serves data; "
                 "no search is run. Feasibility seam only — NOT a candidate and NOT a "
                 "strength/Kaggle claim."),
        "agents_tested": len(results),
        "all_search_api_complete": search_api_ok,
        "all_feasible": feasible,
        "results": results,
    }
    (EXP / "pass40_search_api_feasibility.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Pass 40 (Part K) — cg Search API Feasibility Smoke", "",
        "_Import + one-step data smoke only — no search / MCTS / torch, no candidate, "
        "not a strength or Kaggle claim._", "",
        f"- generated: {payload['generated_at']}",
        f"- **all_feasible: {feasible}**  all_search_api_complete: {search_api_ok}",
        f"- agents tested: {len(results)}", "",
        "| agent | import | search_api | data_api | enums | card_rows | attack_rows | ok |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        osd = r.get("one_step_data", {})
        lines.append(
            f"| `{r['agent_id']}` | {'yes' if r.get('import_ok') else 'NO'} "
            f"| {'yes' if r.get('search_api_complete') else 'NO'} "
            f"| {'yes' if r.get('data_api_complete') else 'NO'} "
            f"| {'yes' if r.get('enums_complete') else 'NO'} "
            f"| {osd.get('all_card_data_len', '—')} "
            f"| {osd.get('all_attack_len', '—')} "
            f"| {'yes' if r.get('ok') else 'NO ('+str(r.get('error'))+')'} |")
    (EXP / "pass40_search_api_feasibility.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")

    print(f"all_feasible={feasible} all_search_api_complete={search_api_ok} "
          f"agents={len(results)}")
    for r in results:
        print(f"  {r['agent_id']}: ok={r.get('ok')} "
              f"search_api={r.get('search_api_complete')} "
              f"err={r.get('error')}")
    print(f"wrote {EXP / 'pass40_search_api_feasibility.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
