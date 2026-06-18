"""Tests for the opt-in fast cabt import stub (Pass 7A, Part F).

These never touch the real ``litellm`` / cabt — they stub harmless dummy module
names and monkeypatch the validation hook, so they run anywhere.
"""

from __future__ import annotations

import sys

import pytest

from ptcg_activegraph.sim import kaggle_import_optimization as opt


@pytest.fixture()
def fake_prefixes():
    names = ["ptcg_fake_heavy_a", "ptcg_fake_heavy_b"]
    yield names
    # cleanup any leftover stubs
    for n in names:
        sys.modules.pop(n, None)


def test_importing_module_does_not_mutate_global_state(fake_prefixes):
    # Merely importing the optimization module must not insert any stubs.
    for n in fake_prefixes:
        assert n not in sys.modules


def test_enable_is_opt_in_and_inserts_only_when_called(fake_prefixes):
    for n in fake_prefixes:
        assert n not in sys.modules
    state = opt.enable_fast_cabt_import_stub(fake_prefixes, validate=False)
    assert state.enabled is True
    assert state.fast_import_stub_enabled is True
    for n in fake_prefixes:
        assert n in sys.modules
        assert getattr(sys.modules[n], "__ptcg_fast_import_stub__", False) is True
    opt.disable_fast_cabt_import_stub(state)


def test_disable_removes_only_inserted_stubs(fake_prefixes):
    state = opt.enable_fast_cabt_import_stub(fake_prefixes, validate=False)
    opt.disable_fast_cabt_import_stub(state)
    for n in fake_prefixes:
        assert n not in sys.modules
    assert state.enabled is False
    assert state.inserted == []


def test_already_imported_module_is_not_clobbered():
    import types

    name = "ptcg_already_here"
    sentinel = types.ModuleType(name)
    sentinel.marker = "real"
    sys.modules[name] = sentinel
    try:
        state = opt.enable_fast_cabt_import_stub([name], validate=False)
        # It must be skipped, not replaced.
        assert name in state.skipped_already_imported
        assert sys.modules[name] is sentinel
        opt.disable_fast_cabt_import_stub(state)
        # disable must NOT remove a module it didn't insert
        assert sys.modules[name] is sentinel
    finally:
        sys.modules.pop(name, None)


def test_metadata_records_flag_and_modules(fake_prefixes):
    state = opt.enable_fast_cabt_import_stub(fake_prefixes, validate=False)
    md = state.metadata()
    assert md["fast_import_stub_enabled"] is True
    assert set(md["stubbed_modules"]) == set(fake_prefixes)
    opt.disable_fast_cabt_import_stub(state)


def test_validation_failure_triggers_graceful_fallback(fake_prefixes, monkeypatch):
    monkeypatch.setattr(
        opt, "validate_fast_import",
        lambda control_dir=None: {"ok": False, "error": "no cabt"},
    )
    state = opt.enable_fast_cabt_import_stub(fake_prefixes, validate=True)
    # Validation failed => stubs rolled back, fallback to normal import.
    assert state.enabled is False
    assert state.fast_import_stub_enabled is False
    for n in fake_prefixes:
        assert n not in sys.modules
    assert state.validation["ok"] is False


def test_validation_success_keeps_stubs(fake_prefixes, monkeypatch):
    monkeypatch.setattr(
        opt, "validate_fast_import",
        lambda control_dir=None: {"ok": True, "smoke_game": True},
    )
    state = opt.enable_fast_cabt_import_stub(fake_prefixes, validate=True)
    assert state.enabled is True
    for n in fake_prefixes:
        assert n in sys.modules
    opt.disable_fast_cabt_import_stub(state)


def test_validate_fast_import_handles_missing_kaggle(monkeypatch):
    # Force the import to fail and confirm we report ok=False without raising.
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "kaggle_environments":
            raise ImportError("simulated missing")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    out = opt.validate_fast_import()
    assert out["ok"] is False
    assert out["import_kaggle_environments"] is False
    assert "simulated missing" in out["error"]
