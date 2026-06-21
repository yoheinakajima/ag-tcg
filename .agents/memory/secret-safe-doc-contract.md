---
name: secret-safe doc/contract validation
description: how to prove a committed doc (e.g. a dashboard data contract) leaks no secret without ever emitting a secret value
---

# Secret-safe committed-doc validation

When a pass must publish a NON-SECRET document into the repo (e.g. a dashboard data
contract describing object-storage keys), validate its secret-safety like this:

- Read the live secret VALUES from `os.environ` **only to assert their ABSENCE** as a
  substring of the doc text. NEVER print, log, or write those values — report only the
  env var NAMES that leaked (empty list = clean).
- Also reject value-shaped patterns regardless of env: `replit-objstore-<hex>` bucket
  ids, long hex tokens (`\b[0-9a-f]{32,}\b`), `AKIA…` access keys.
- The doc may reference env var NAMES (`DEFAULT_OBJECT_STORAGE_BUCKET_ID`,
  `TOURNAMENT_STORAGE_PREFIX`) and RELATIVE keys (full key = `<prefix>/<rel>`); names and
  relative keys are not secrets. Show projection/event shapes with PLACEHOLDER values only
  (no real sha/fingerprints).

**Why:** a naive "grep the doc for the word secret/token" both false-positives on prose
and false-negatives on real leaked values. Asserting absence of the actual env values +
value-shaped regex is the honest test; emitting the value to check it would itself be the
leak.

**How to apply:** any future "publish a contract / handoff doc" pass. Pair the check with
a key-parity check: list prod keys NAMES only (`backend.list("")`, no body downloads) and
assert every documented exact key/prefix is present. Verify ALL documented exact keys
(incl. `config.yaml` and every projection), not a subset, or parity silently passes on
undocumented drift.
