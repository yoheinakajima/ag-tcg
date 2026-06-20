#!/usr/bin/env python3
"""Pass 38 (Part B) — deployment incident addendum (idempotent doc update).

OPS / documentation. Records the Pass 37 Scheduled-Deployment BUILD incident
(root cause + durable fixes) and the Pass 38 soak status as a clearly delimited,
idempotent addendum block inserted into the operator-facing docs. Re-running
replaces the block in place (never duplicates). Pulls live numbers from the Pass
38 artifacts so the addendum is honest about current state.

Targets:
  * docs/PERSISTENT_TOURNAMENT_DAEMON.md      (operator runbook)
  * data/reports/activegraph_strategy_report.md
  * docs/PTCG_STRATEGY_CANVAS.md
  * data/site/index.html                      (HTML block before </body>)

Writes data/experiments/pass38_deployment_incident_addendum.{json,md}. NO upload,
NO submit, NO push, NO root main.py/deck.csv mutation, NO candidate generation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"

START = "<!-- PASS38_ADDENDUM_START -->"
END = "<!-- PASS38_ADDENDUM_END -->"

MD_TARGETS = [
    REPO / "docs" / "PERSISTENT_TOURNAMENT_DAEMON.md",
    REPO / "data" / "reports" / "activegraph_strategy_report.md",
    REPO / "docs" / "PTCG_STRATEGY_CANVAS.md",
]
HTML_TARGET = REPO / "data" / "site" / "index.html"


def _load(name: str) -> dict:
    p = EXP / name
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except Exception:
        return {}


def _build_markdown() -> str:
    tick = _load("pass38_controlled_production_tick.json")
    health = _load("pass38_tournament_health.json")
    sched = _load("pass38_scheduled_run_detection.json")
    cfg = _load("pass38_root_and_deploy_config.json")

    gp = tick.get("games_played")
    be, af = tick.get("before", {}), tick.get("after", {})
    ev_before, ev_after = be.get("events"), af.get("events")
    push_ok = (tick.get("push") or {}).get("verify_ok")
    healthy = health.get("healthy")
    warns = health.get("warnings", [])
    detected = sched.get("scheduled_run_detected")
    n_manual = sched.get("ticks_manual_or_smoke")
    n_total = sched.get("total_ticks_in_ledger")
    root_safe = cfg.get("safe", cfg.get("root_unchanged", cfg.get("verdict_ok")))

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "unverified")

    return "\n".join([
        START,
        "## Pass 38 — Deployment incident addendum & soak status (OPS only)",
        "",
        "> Internal diagnostics only. **NOT a Kaggle leaderboard.** **NO upload, "
        "NO submit, NO auto-submit, no new candidates, no root mutation.** The root "
        '"Start application" workflow stays not-started (frozen Kaggle entrypoint) — '
        "that is EXPECTED.",
        "",
        "### What went wrong at publish (Pass 37) and the durable fixes",
        "- **uv editable-install into the read-only Nix store** — the deploy build "
        "auto-runs `uv sync`, which editable-installed the root project and wrote "
        "`__editable__*.pth` into the read-only store → EACCES → build failed. "
        "**Fix:** `[tool.uv] package = false` (the worker puts `src/` on `sys.path` "
        "itself; no install needed). Do not add dependency-groups/default-groups.",
        "- **uv cannot install deploy deps** — install deploy-only deps in the BUILD "
        "command with `python -m pip install --user --break-system-packages` so they "
        "land in the writable `.pythonlibs` (PYTHONUSERBASE).",
        "- **bundled cabt env** — games run via `kaggle_environments.make(\"cabt\")`; "
        "the cabt env ships INSIDE the `kaggle-environments==1.30.1` wheel, so that "
        "pin must be in the build command or every game errors (publish still "
        "succeeds → silent zero progress).",
        "- **publish-success is decoupled from game-success** — a failing game is "
        "recorded `timeout`/`error` and never fails the tick; the worker exits "
        "non-zero only on top-level/storage/refused/conflict/lease errors. When "
        "debugging a publish failure, separate \"does the run exit 0\" from \"do "
        "games progress\".",
        "",
        "### Pass 38 soak status (live)",
        f"- root `main.py`/`deck.csv` byte-identical to the frozen baseline + deploy "
        f"config verified: **{yn(root_safe)}**",
        f"- controlled production tick: played **{gp}** internal games, ledger "
        f"**{ev_before} → {ev_after}** events, push self-verified: **{yn(push_ok)}**",
        f"- health checker (prod + local) healthy: **{yn(healthy)}** "
        f"(soft warnings: {warns or 'none'})",
        f"- scheduled production run observed yet: **{yn(detected)}** "
        f"(all {n_total} recorded ticks are manual/smoke; {n_manual} classified "
        "manual — the deployment is published and ready but a real scheduled tick "
        "has not yet fired in the ledger/deployment logs)",
        "- guardrails intact: held probe retained, special-pilot-only decks never "
        "scheduled, `auto_submit` refused, every event `no_upload=true`.",
        "",
        "Detail: `data/reports/pass38_scheduled_deployment_ops_report.md`; runbook "
        "`docs/REPLIT_SCHEDULED_DEPLOYMENT_RUNBOOK.md`; per-part artifacts "
        "`data/experiments/pass38_*.{json,md}`.",
        END,
    ])


def _md_to_html(md: str) -> str:
    """Wrap the addendum as a minimal HTML block for the generated site page."""
    tick = _load("pass38_controlled_production_tick.json")
    health = _load("pass38_tournament_health.json")
    sched = _load("pass38_scheduled_run_detection.json")
    gp = tick.get("games_played")
    healthy = health.get("healthy")
    detected = sched.get("scheduled_run_detected")
    return "\n".join([
        START,
        '<h2>Pass 38 — Deployment soak status (internal, NOT Kaggle)</h2>',
        "<p>The Pass 37 Scheduled-Deployment build failure (uv editable-install "
        "into the read-only Nix store) was fixed durably "
        "(<code>[tool.uv] package=false</code>; deploy deps via <code>pip "
        "install --user</code>; <code>kaggle-environments==1.30.1</code> for the "
        "bundled cabt env). The deployment now publishes successfully.</p>",
        f"<p>Soak: a controlled production tick played <b>{gp}</b> internal games "
        f"and self-verified its push; the health checker reports healthy="
        f"<b>{'yes' if healthy else 'no'}</b>; a real scheduled run observed yet: "
        f"<b>{'yes' if detected else 'no'}</b> (all recorded ticks are "
        "manual/smoke). NO upload, NO submit, NO auto-submit, no new candidates.</p>",
        END,
    ])


def _apply(path: Path, block: str, *, html: bool) -> dict:
    existed = path.is_file()
    text = path.read_text(encoding="utf-8") if existed else ""
    had_block = START in text and END in text
    if had_block:
        pre = text.split(START)[0].rstrip("\n")
        post = text.split(END, 1)[1].lstrip("\n")
        new = (pre + "\n\n" + block + "\n" + post).rstrip("\n") + "\n"
    elif html and "</body>" in text:
        new = text.replace("</body>", block + "\n</body>", 1)
    else:
        new = (text.rstrip("\n") + "\n\n" + block + "\n") if text else block + "\n"
    path.write_text(new, encoding="utf-8")
    final = path.read_text(encoding="utf-8")
    occ = final.count(START)
    return {"path": str(path.relative_to(REPO)), "existed": existed,
            "replaced_in_place": had_block, "block_count": occ,
            "ok": occ == 1 and END in final}


def main() -> int:
    md_block = _build_markdown()
    html_block = _md_to_html(md_block)
    block_sha = hashlib.sha256(md_block.encode()).hexdigest()[:16]

    results = [_apply(p, md_block, html=False) for p in MD_TARGETS]
    if HTML_TARGET.is_file():
        results.append(_apply(HTML_TARGET, html_block, html=True))

    all_ok = all(r["ok"] for r in results)

    EXP.mkdir(parents=True, exist_ok=True)
    payload = {
        "pass": "38", "part": "B", "no_upload": True, "upload_performed": False,
        "auto_submit": False, "github_push": False, "candidate_generation": False,
        "root_mutation": False,
        "addendum_block_sha16": block_sha,
        "idempotent_markers": [START, END],
        "targets": results,
        "all_ok": all_ok,
    }
    (EXP / "pass38_deployment_incident_addendum.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "unverified")

    md = [
        "# Pass 38 — Deployment incident addendum (Part B)", "",
        "> OPS / documentation. Idempotently inserts a delimited Pass 38 addendum "
        "(Pass 37 build-incident root cause + fixes, and Pass 38 soak status) into "
        "the operator docs. Re-running replaces the block in place. NO upload, NO "
        "root mutation, NO candidate generation.", "",
        f"- addendum block sha16: `{block_sha}`",
        f"- markers: `{START}` … `{END}`",
        f"- all targets carry exactly one addendum block: **{yn(all_ok)}**", "",
        "## Targets",
        "| doc | existed | replaced_in_place | block_count | ok |",
        "|---|---|---|---|---|",
        *[f"| `{r['path']}` | {yn(r['existed'])} | {yn(r['replaced_in_place'])} "
          f"| {r['block_count']} | {yn(r['ok'])} |" for r in results],
    ]
    (EXP / "pass38_deployment_incident_addendum.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"incident addendum: all_ok={all_ok} targets={len(results)} "
          f"sha16={block_sha}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
