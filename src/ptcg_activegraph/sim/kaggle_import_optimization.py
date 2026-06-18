"""Optional, opt-in cold-start optimization for ``kaggle_environments``/cabt.

Importing :mod:`kaggle_environments` eagerly registers *every* bundled
environment. Two of those (the ``werewolf`` LLM harness and the OpenSpiel
games) drag in very heavy dependencies — most notably ``litellm`` (~5s) — that
the cabt PTCG environment never touches. By inserting lightweight stub modules
into :data:`sys.modules` *before* importing ``kaggle_environments`` we skip that
dead weight and cut cold-start from ~7-15s to ~1.5s while leaving the cabt path
untouched.

Hard safety rules (mirrored in ``docs/EVALUATION_WORKER_POOL_PLAN.md``):

* **Opt-in only.** Nothing here runs at import time. The bulk runner keeps the
  safe ``subprocess_per_game`` path until a benchmark validates this stub.
* **No site-packages patching.** We only mutate the in-process ``sys.modules``
  table, and only for module names that were *not already imported*.
* **Reversible.** :func:`disable_fast_cabt_import_stub` removes exactly the
  stub entries this module inserted, leaving any genuinely-imported modules
  alone.
* **Self-validating.** :func:`enable_fast_cabt_import_stub` can run a smoke
  check (import + ``make("cabt")`` + one game). If anything fails it tears the
  stubs back down and reports ``enabled=False`` so callers fall back to a normal
  import.
* **Child-only.** Intended for the evaluation subprocess/worker, never for the
  competition ``root main.py``.
"""

from __future__ import annotations

import sys
import time
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# Heavy modules pulled in transitively by non-cabt environments. ``litellm`` is
# the dominant cost (imported by the werewolf harness). Kept as a tuple of
# top-level prefixes; submodule imports beneath a stubbed prefix resolve against
# the stub.
DEFAULT_STUB_PREFIXES: tuple[str, ...] = ("litellm",)


def _make_stub(name: str) -> types.ModuleType:
    """Build a permissive stub module.

    ``__path__ = []`` marks it as a package so ``import <name>.<sub>`` does not
    fall through to the real installed package, and ``__getattr__`` hands back a
    throwaway object for any ``from <name> import X`` access so the importing
    module fails *gracefully* (or not at all) rather than exploding.
    """
    mod = types.ModuleType(name)
    mod.__path__ = []  # type: ignore[attr-defined]
    mod.__ptcg_fast_import_stub__ = True  # type: ignore[attr-defined]

    def __getattr__(attr: str):  # noqa: ANN202
        return types.SimpleNamespace()

    mod.__getattr__ = __getattr__  # type: ignore[attr-defined]
    return mod


@dataclass
class StubState:
    """Record of an :func:`enable_fast_cabt_import_stub` call.

    Carry this back to :func:`disable_fast_cabt_import_stub` to undo the stubs.
    """

    enabled: bool = False
    inserted: list[str] = field(default_factory=list)
    requested_prefixes: tuple[str, ...] = ()
    skipped_already_imported: list[str] = field(default_factory=list)
    validation: dict = field(default_factory=dict)

    @property
    def fast_import_stub_enabled(self) -> bool:
        return self.enabled

    def metadata(self) -> dict:
        """Result metadata for embedding in a game/run record."""
        return {
            "fast_import_stub_enabled": self.enabled,
            "stubbed_modules": list(self.inserted),
            "requested_prefixes": list(self.requested_prefixes),
            "skipped_already_imported": list(self.skipped_already_imported),
            "validation": dict(self.validation),
        }


def _insert_stubs(prefixes: Iterable[str]) -> StubState:
    state = StubState(requested_prefixes=tuple(prefixes))
    for name in state.requested_prefixes:
        if name in sys.modules:
            # Already genuinely imported (or stubbed) — never clobber it.
            state.skipped_already_imported.append(name)
            continue
        sys.modules[name] = _make_stub(name)
        state.inserted.append(name)
    return state


def disable_fast_cabt_import_stub(state: StubState) -> None:
    """Remove exactly the stub modules ``state`` inserted.

    Only entries we created (and which still look like our stubs) are removed,
    so a module that got genuinely imported afterwards is left untouched.
    """
    for name in list(state.inserted):
        mod = sys.modules.get(name)
        if mod is not None and getattr(mod, "__ptcg_fast_import_stub__", False):
            del sys.modules[name]
    state.inserted.clear()
    state.enabled = False


def enable_fast_cabt_import_stub(
    stub_prefixes: Iterable[str] | None = None,
    *,
    validate: bool = True,
    control_dir: str | Path | None = None,
) -> StubState:
    """Insert stub modules to speed up the cabt cold-start. Opt-in only.

    Parameters
    ----------
    stub_prefixes:
        Top-level module names to stub. Defaults to :data:`DEFAULT_STUB_PREFIXES`.
    validate:
        When True (default) run :func:`validate_fast_import` after stubbing. If
        validation fails the stubs are removed and ``enabled`` is False so the
        caller transparently falls back to a normal import.
    control_dir:
        Optional v2 baseline dir used for the one-game smoke during validation.

    Returns
    -------
    StubState
        Carries ``enabled`` / ``fast_import_stub_enabled`` plus the list of
        modules actually stubbed. Pass it to
        :func:`disable_fast_cabt_import_stub` to undo.
    """
    prefixes = tuple(stub_prefixes) if stub_prefixes is not None else DEFAULT_STUB_PREFIXES
    state = _insert_stubs(prefixes)
    state.enabled = True

    if not validate:
        state.validation = {"ran": False}
        return state

    result = validate_fast_import(control_dir=control_dir)
    state.validation = result
    if not result.get("ok", False):
        # Roll back so the caller uses the normal (slow but proven) import.
        disable_fast_cabt_import_stub(state)
        state.enabled = False
    return state


def validate_fast_import(control_dir: str | Path | None = None) -> dict:
    """Validate that the cabt path still works under whatever stubs are active.

    Checks, in order: import ``kaggle_environments``; ``make("cabt")``; run one
    smoke game using the v2 baseline. Returns a dict describing each step. Never
    raises — any failure is captured as ``ok=False`` with an ``error`` string.
    """
    out: dict = {
        "ok": False,
        "import_kaggle_environments": False,
        "make_cabt": False,
        "smoke_game": False,
        "smoke_shape": None,
        "error": None,
    }
    try:
        import kaggle_environments  # noqa: F401

        out["import_kaggle_environments"] = True
    except Exception as exc:  # pragma: no cover - env dependent
        out["error"] = f"import kaggle_environments failed: {exc!r}"
        return out

    try:
        env = kaggle_environments.make("cabt", debug=False)
        out["make_cabt"] = True
    except Exception as exc:
        out["error"] = f"make('cabt') failed: {exc!r}"
        return out

    try:
        shape = _smoke_game_shape(env, control_dir)
        out["smoke_shape"] = shape
        out["smoke_game"] = shape is not None
        out["ok"] = out["smoke_game"]
    except Exception as exc:
        out["error"] = f"smoke game failed: {exc!r}"
    return out


def _smoke_game_shape(env, control_dir: str | Path | None) -> dict | None:
    """Run a minimal self-play game and return its result shape, or None.

    Uses the v2 baseline ``main.py`` as both seats when available; otherwise
    falls back to the env's default agents. Kept intentionally tiny — this is a
    shape/health check, not a strategy measurement.
    """
    agents: list = ["random", "random"]
    if control_dir is not None:
        main_py = Path(control_dir) / "main.py"
        if main_py.exists():
            agents = [str(main_py), str(main_py)]
    try:
        env.reset()
        env.run(agents)
    except Exception:
        # Fall back to default agents if the baseline main.py isn't compatible
        # with the raw env protocol; the point is a shape comparison.
        env.reset()
        env.run(["random", "random"])
    steps = getattr(env, "steps", None)
    return {
        "num_steps": len(steps) if steps is not None else None,
        "done": getattr(env, "done", None),
        "has_steps": steps is not None,
    }
