"""Optional cabt-backed search policy.

Disabled by default. The runtime agent only consults this when:

* ``cabt`` search APIs are importable, **and**
* search has been explicitly enabled, **and**
* there is time budget remaining.

It must *never* crash the runtime. Search resources are always released in a
``finally`` block. When cabt is unavailable, :meth:`SearchPolicy.suggest`
returns ``None`` so the caller falls through to the heuristic/fallback path.
"""

from __future__ import annotations

from typing import Any

from .time_manager import TimeManager


def cabt_search_available() -> bool:
    """Detect whether the cabt search API surface is importable."""
    try:
        import cabt  # type: ignore  # noqa: F401
    except Exception:
        return False
    required = ("search_begin", "search_step", "search_end", "search_release")
    try:
        return all(hasattr(cabt, name) for name in required)
    except Exception:  # pragma: no cover - extremely defensive
        return False


class SearchPolicy:
    """Shallow cabt search wrapper, off unless explicitly enabled."""

    def __init__(self, enabled: bool = False, depth: int = 1, soft_budget_s: float = 0.3) -> None:
        self.enabled = bool(enabled)
        self.depth = max(1, int(depth))
        self.soft_budget_s = float(soft_budget_s)
        self._available: bool | None = None

    def available(self) -> bool:
        if self._available is None:
            self._available = cabt_search_available()
        return self._available

    def suggest(
        self,
        observation: Any,
        legal_indices: list[int],
        max_count: int,
        time_manager: TimeManager | None = None,
    ) -> list[int] | None:
        """Return a search-derived selection, or ``None`` to defer.

        This is a guarded skeleton: when search is enabled and cabt is present
        it would call ``search_begin``/``search_step`` to evaluate candidate
        actions. Until that path is validated it conservatively returns
        ``None`` so the heuristic policy decides. It is structured so wiring in
        the real evaluation only touches the marked block.
        """
        if not self.enabled or not self.available():
            return None
        if time_manager is not None and not time_manager.has_budget(0.5):
            return None

        search_id = None
        try:
            import cabt  # type: ignore

            # --- begin search-evaluation seam (not yet validated) -----------
            # search_id = cabt.search_begin(...)
            # for candidate in legal_indices: evaluate via cabt.search_step
            # pick best; for now we defer to the heuristic policy.
            # ----------------------------------------------------------------
            return None
        except Exception:
            return None
        finally:
            if search_id is not None:
                try:
                    import cabt  # type: ignore

                    cabt.search_release(search_id)
                except Exception:
                    pass
