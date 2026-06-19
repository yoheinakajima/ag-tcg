"""Pass 21 — Kaggle replay ingestion + Water reference post-mortem.

Targeted guardrail/integrity tests for the 12 checks in the Pass 21 instructions
(Part L). ANALYSIS/REPORTING ONLY: these tests assert that the recorded Pass 21
artifacts are internally consistent, evidence-backed, and that every no-upload /
root-immutability guardrail held.
"""

from __future__ import annotations

import csv
import filecmp
import json
import subprocess
from pathlib import Path

import pytest

try:
    import yaml
except Exception:  # pragma: no cover - yaml is available in the runtime
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"
META = ROOT / "data" / "meta_replays"
RAW = META / "raw"
REPORTS = ROOT / "data" / "reports"

NEW_EPISODE_IDS = ["80590776", "80591511", "80592173", "80592831", "80593320"]
PRE_EXISTING_TRACKED = "80374966_self_mirror.json"


def _load(path: Path):
    return json.loads(path.read_text())


@pytest.fixture(scope="module")
def ingestion():
    return _load(EXP / "pass21_replay_ingestion.json")


@pytest.fixture(scope="module")
def analysis():
    return _load(EXP / "pass21_water_replay_analysis.json")


@pytest.fixture(scope="module")
def archetypes():
    return _load(EXP / "pass21_archetype_updates.json")


@pytest.fixture(scope="module")
def taxonomy():
    return _load(EXP / "pass21_water_failure_taxonomy.json")


@pytest.fixture(scope="module")
def probe():
    return _load(EXP / "pass21_water_probe_status.json")


@pytest.fixture(scope="module")
def registry():
    return _load(META / "replay_registry.json")


def _registry_episode_ids(registry) -> set[str]:
    ids: set[str] = set()
    for rec in registry.get("records", []):
        for key in ("episode_id", "EpisodeId", "episode", "id"):
            if key in rec and rec[key] is not None:
                ids.add(str(rec[key]))
                break
    return ids


def _known_episode_ids(registry) -> set[str]:
    ids = _registry_episode_ids(registry)
    ids.update(NEW_EPISODE_IDS)
    return ids


# 1. raw replay files are gitignored
def test_raw_replay_files_are_gitignored(ingestion):
    status = ingestion["raw_replay_gitignore_status"]
    assert status["new_replays_all_gitignored"] is True
    assert status["pre_existing_tracked"] == [PRE_EXISTING_TRACKED]

    for epid in NEW_EPISODE_IDS:
        raw = RAW / f"{epid}.json"
        if not raw.exists():
            continue
        res = subprocess.run(
            ["git", "check-ignore", str(raw.relative_to(ROOT))],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"raw replay {epid}.json is NOT gitignored"

    # The one explicitly-approved pre-existing replay is the only tracked exception.
    res = subprocess.run(
        ["git", "check-ignore", f"data/meta_replays/raw/{PRE_EXISTING_TRACKED}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1, "pre-existing approved self-mirror should be tracked"


# 2. ingestion dedupes by EpisodeId
def test_ingestion_dedupes_by_episode_id(ingestion, registry):
    assert ingestion["duplicates_skipped"] == 0
    assert ingestion["failed_parses"] == 0
    ids = [
        str(rec.get("episode_id") or rec.get("EpisodeId") or rec.get("episode") or rec.get("id"))
        for rec in registry.get("records", [])
    ]
    assert len(ids) == len(set(ids)), "registry contains duplicate EpisodeIds"


# 3. new EpisodeIds are preserved in registry
def test_new_episode_ids_preserved_in_registry(ingestion, registry):
    assert ingestion["new_episode_ids"] == NEW_EPISODE_IDS
    reg_ids = _registry_episode_ids(registry)
    missing = [e for e in NEW_EPISODE_IDS if e not in reg_ids]
    assert not missing, f"registry missing new episodes: {missing}"


# 4. replay analysis includes all newly added episodes
def test_analysis_includes_all_new_episodes(analysis):
    analyzed = {str(g["episode"]) for g in analysis["per_game"]}
    new_listed = {str(e) for e in analysis["new_episodes"]}
    for epid in NEW_EPISODE_IDS:
        assert epid in new_listed, f"{epid} missing from analysis.new_episodes"
        assert epid in analyzed, f"{epid} missing from analysis.per_game"


# 5. Water replay analysis does not fabricate card IDs
def test_water_analysis_does_not_fabricate_card_ids(archetypes):
    card_db = ROOT / "data" / "cards" / "EN_Card_Data.csv"
    valid_ids: set[int] = set()
    if card_db.exists():
        with card_db.open(newline="") as fh:
            for row in csv.DictReader(fh):
                raw = (row.get("Card ID") or "").strip()
                if raw.isdigit():
                    valid_ids.add(int(raw))

    for arch in archetypes["new_or_updated_archetypes"]:
        ids = arch.get("signature_card_ids", [])
        names = arch.get("signature_card_names", [])
        assert ids, f"{arch['archetype_id']} has no signature card ids"
        assert len(ids) == len(names), (
            f"{arch['archetype_id']} id/name length mismatch (would imply invented data)"
        )
        for cid in ids:
            assert isinstance(cid, int), f"non-integer card id {cid!r}"
            if valid_ids:
                assert cid in valid_ids, (
                    f"fabricated card id {cid} in {arch['archetype_id']} (not in card DB)"
                )


# 6. archetype updates have evidence episodes
def test_archetype_updates_have_evidence_episodes(archetypes, registry):
    known = _known_episode_ids(registry)
    for arch in archetypes["new_or_updated_archetypes"]:
        ev = arch.get("evidence_episode_ids", [])
        assert ev, f"{arch['archetype_id']} has no evidence episodes"
        for epid in ev:
            assert str(epid) in known, f"{arch['archetype_id']} cites unknown episode {epid}"


# 7. failure taxonomy has counts and evidence
def test_failure_taxonomy_has_counts_and_evidence(taxonomy, registry):
    known = _known_episode_ids(registry)
    tags = taxonomy["tags"]
    assert tags, "failure taxonomy has no tags"
    assert any(t["count"] >= 1 for t in tags), "taxonomy records no observed modes"
    for tag in tags:
        assert isinstance(tag["count"], int) and tag["count"] >= 0
        assert tag.get("evidence"), f"tag {tag['tag']} missing evidence"
        eps = tag.get("episodes", [])
        # count-0 tags are faithfully recorded as 'not observed' with no episodes.
        assert tag["count"] == len(eps), f"tag {tag['tag']} count != episode list length"
        for epid in eps:
            assert str(epid) in known, f"tag {tag['tag']} cites unknown episode {epid}"


# 8. planned fixtures reference real episode IDs
def test_planned_fixtures_reference_real_episodes(registry):
    assert yaml is not None
    data = yaml.safe_load((ROOT / "data" / "fixtures" / "pass21_planned_water_fixtures.yaml").read_text())
    assert data.get("not_implemented_this_pass") is True
    known = _known_episode_ids(registry)
    fixtures = data["fixtures"]
    assert fixtures, "no planned fixtures"
    for fx in fixtures:
        assert fx.get("implemented") is False, f"fixture {fx['id']} must not be implemented this pass"
        src = str(fx["source_episode"])
        assert src in known, f"fixture {fx['id']} references unknown episode {src}"


# 9. score status refresh is read-only
def test_score_status_refresh_is_read_only(probe):
    assert probe["read_only"] is True
    assert probe["upload_performed"] is False
    assert probe["probe_status"] == "complete"


# 10. no upload flag remains false
def test_no_upload_flag_remains_false(probe):
    assert probe["upload_performed"] is False

    interp = _load(EXP / "pass21_strategy_interpretation.json")
    assert interp["no_upload"] is True

    events_path = ROOT / "data" / "activegraph" / "lab_events.jsonl"
    pass21_events = 0
    for line in events_path.read_text().splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        payload = ev.get("payload", {})
        is_pass21 = "pass21" in (ev.get("tags") or []) or payload.get("pass") in (21, "21")
        if is_pass21:
            pass21_events += 1
            assert "no_upload" in payload, f"event {ev.get('event_type')} missing no_upload flag"
            assert payload["no_upload"] is True, f"event {ev.get('event_type')} has no_upload != true"
    assert pass21_events >= 1, "expected at least one Pass 21 event"


# 11. root files unchanged
def test_root_files_unchanged():
    baseline = ROOT / "data" / "baselines" / "v1_kaggle_349_8"
    assert filecmp.cmp(ROOT / "main.py", baseline / "main.py", shallow=False), "root main.py drifted"
    assert filecmp.cmp(ROOT / "deck.csv", baseline / "deck.csv", shallow=False), "root deck.csv drifted"


# 12. report includes replay-derived evidence caveat
def test_report_includes_replay_derived_evidence_caveat():
    report = (REPORTS / "pass21_water_reference_replay_analysis_report.md").read_text()
    low = report.lower()
    assert "replay-derived evidence caveat" in low
    assert "trusted over" in low or "trust" in low
    # Must not erase Pass 20 facts.
    assert "pass 20" in low or "pass20" in low
