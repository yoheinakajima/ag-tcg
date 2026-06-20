"""Pass 36 — Standing ActiveGraph Tournament Engine v0.

A persistent, event-first, resumable, bounded tournament engine built on top of
the proven repo substrate (graph EventStore, experiments game runner, candidate
tarballs). It does NOT generate candidates and does NOT upload/submit anything.
Internal tournament scores are local diagnostics only and are NOT a Kaggle
leaderboard.
"""

from __future__ import annotations

TOURNAMENT_VERSION = "v0"
NO_UPLOAD = True
