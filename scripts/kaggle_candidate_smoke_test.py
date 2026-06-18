#!/usr/bin/env python3
"""Real cabt smoke test for a candidate TARBALL's own main.py + deck.csv.

Unlike ``scripts/kaggle_smoke_test.py`` (which runs the *repo root* runtime agent
against a deck file), this extracts the candidate tarball, imports the extracted
``main.py``, loads the extracted ``deck.csv``, builds a real
``kaggle_environments.make("cabt", ...)`` env, and runs
``env.run([candidate_agent, candidate_agent])``.

It then inspects every step's per-agent ``status`` so a game that *completes* but
with INVALID/ERROR/TIMEOUT (exactly the Kaggle pre-game failure mode that a deck
return of ``[]`` produces) is reported as FAIL — the repo-runtime smoke could not
catch that because it never ran the tarball's own main.py.

Exit code 0 on PASS, 1 on FAIL.

Usage:
    python scripts/kaggle_candidate_smoke_test.py PATH/TO/candidate.tar.gz
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tarfile
import tempfile
import traceback
from pathlib import Path

import _bootstrap  # noqa: F401  (adds repo + src to sys.path)

BAD_STATUSES = {"INVALID", "ERROR", "TIMEOUT"}


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _load_extracted_agent(tmp_dir: Path):
    main_path = tmp_dir / "main.py"
    sys.path.insert(0, str(tmp_dir))
    spec = importlib.util.spec_from_file_location("candidate_smoke_main",
                                                  main_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["candidate_smoke_main"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _read_deck(deck_path: Path) -> list[int]:
    return [int(x.strip()) for x in deck_path.read_text(encoding="utf-8")
            .splitlines() if x.strip()]


def _statuses(env) -> list[str]:
    seen: list[str] = []
    for step in getattr(env, "steps", []) or []:
        if not isinstance(step, list):
            continue
        for agent_state in step:
            status = None
            if isinstance(agent_state, dict):
                status = agent_state.get("status")
            else:
                status = getattr(agent_state, "status", None)
            if status is not None:
                seen.append(str(status))
    return seen


def smoke(tarball: str, out_dir: str) -> int:
    tb = Path(tarball)
    if not tb.exists():
        return _fail(f"tarball not found: {tb}")

    try:
        from kaggle_environments import make  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return _fail(f"kaggle_environments unavailable: {exc!r}")

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        try:
            with tarfile.open(tb, "r:gz") as tar:
                tar.extractall(tmp_dir)  # noqa: S202
        except Exception as exc:  # noqa: BLE001
            return _fail(f"could not extract tarball: {exc!r}")

        main_path = tmp_dir / "main.py"
        deck_path = tmp_dir / "deck.csv"
        if not main_path.exists() or not deck_path.exists():
            return _fail("tarball missing main.py or deck.csv")

        deck = _read_deck(deck_path)
        if len(deck) != 60:
            return _fail(f"deck.csv has {len(deck)} cards, expected 60")

        old_cwd = os.getcwd()
        os.chdir(tmp_dir)  # so the candidate's own deck.csv resolves
        try:
            try:
                mod = _load_extracted_agent(tmp_dir)
            except Exception as exc:  # noqa: BLE001
                return _fail(f"could not import extracted main.py: {exc!r}")
            if not hasattr(mod, "agent") or not callable(mod.agent):
                return _fail("extracted main.py has no callable agent()")
            agent = mod.agent

            env = None
            last_err = None
            for cfg in ({"decks": [deck, deck]}, {"deck": deck}, {}):
                try:
                    env = make("cabt", configuration=cfg)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_err = exc
            if env is None:
                return _fail(f"make('cabt', ...) failed: {last_err!r}")

            try:
                env.run([agent, agent])
            except Exception:  # noqa: BLE001
                print(traceback.format_exc())
                return _fail("env.run raised")

            statuses = _statuses(env)
            bad = sorted({s for s in statuses if s in BAD_STATUSES})
            n_steps = len(getattr(env, "steps", []) or [])

            # Persist the result for provenance.
            summary = {
                "tarball": str(tb),
                "status": "FAIL" if bad else "PASS",
                "steps": n_steps,
                "bad_statuses": bad,
                "final_statuses": statuses[-2:] if statuses else [],
                "deck_size": len(deck),
            }
            stem = tb.name.replace(".tar.gz", "").replace(".tgz", "")
            (out_path / f"candidate_smoke_{stem}.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8")
            try:
                html = env.render(mode="html")  # type: ignore[call-arg]
                if html:
                    (out_path / f"candidate_smoke_{stem}.html").write_text(
                        str(html), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass

            if bad:
                return _fail(f"game produced bad statuses {bad} over {n_steps} "
                             f"steps (see candidate_smoke_{stem}.json)")
        finally:
            os.chdir(old_cwd)
            sys.path[:] = [p for p in sys.path if p != str(tmp_dir)]
            sys.modules.pop("candidate_smoke_main", None)

    print(f"PASS: {tb.name} completed a cabt self-play game over {n_steps} "
          f"steps with no INVALID/ERROR/TIMEOUT")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tarball", help="path to candidate .tar.gz")
    parser.add_argument("--out", default="data/matches")
    args = parser.parse_args()
    return smoke(args.tarball, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
