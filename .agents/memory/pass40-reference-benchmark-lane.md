---
name: reference benchmark lane
description: Intake of untrusted external (public Kaggle) reference agents as benchmark-only opponents — safe tar extraction, separate no_upload ledger/zero-leakage, and seat-balanced bounded worklists.
---

# Public reference agents = untrusted, benchmark-only

External reference agents (public Kaggle competitor submissions) are NOT our
candidates. They are imported purely as **benchmark opponents** and must never
leak into our own competitive machinery.

## Untrusted tarball extraction
Any externally-sourced tarball must be extracted with a member-validating helper
(`safe_extract_all` in `tournament/artifacts.py`), never a bare
`TarFile.extractall`. The helper validates ALL members before extracting and
rejects: absolute paths, `..` traversal (checked via `Path.resolve()` +
`relative_to(dest)`, which also defeats traversal through pre-existing symlinked
dirs), symlinks, hardlinks, and device/FIFO members (`isdev()`).
**Why:** a malicious public submission could otherwise overwrite arbitrary files
on extract. **How to apply:** route every new external-intake extract site
through the shared helper; grep for `extractall(` when adding intake code.

## Lane separation (zero leakage)
References live in a SEPARATE ledger file with their own EventTypes
(`PublicReferenceAgentRegistered`, `PublicBenchmark*`, `CgTypedLaneValidated`),
all stamped `no_upload=true`. They must be absent from: submission queue,
promotion, mutation lineage, lifecycle plan, family-champion, active-cap, and
any "our best"/rankings projection. An integration check asserts this
(`integration_ok` / `zero_leakage` with ~11 sub-checks, run against both a clean
and a poisoned ledger). **Why:** internal benchmark scores are NOT Kaggle scores
and references aren't ours; conflating them corrupts promotion/rankings.

## Seat-balanced bounded worklists
A bounded benchmark worklist (each OUR candidate vs each ref, capped at
`max_games`) must emit BOTH seats for a pair before expanding to the next pair.
**Why:** a naive "one game per pair per pass" loop, when `max_games < 2 × pairs`,
fills the entire cap on the FIRST pass — all seat0, zero seat1 — so a truncated
worklist is seat-imbalanced. Emitting both seats per pair keeps any even cap
balanced (e.g. 40-game cap over 65 pairs → 20 seat0 / 20 seat1). Odd caps end
one game off-balance (unavoidable). Determinism, the `max_games` bound, and
least-played-pair resume are preserved; with pre-existing uneven directed counts
the under-played seat may repeat to repair balance (correct).
