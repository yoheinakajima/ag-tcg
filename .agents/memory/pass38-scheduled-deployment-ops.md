---
name: scheduled-deployment ops & health-checker severity model
description: Durable decisions for the tournament Scheduled Deployment soak/monitoring — manifest-sha severity by mode, "published ≠ observed running", runbook-to-.replit pinning, and the script-as-module test gotcha.
---

# Manifest-sha integrity is severity-by-mode (prod HARD, local WARN)
The health checker's `manifest_sha_integrity` is HARD only in `--mode prod` and a
WARNING in `--mode local`.
**Why:** prod (Object Storage) is the authoritative snapshot — files+manifest are
pushed together, so byte-drift there means real corruption. The local working dir is
*disposable*: any local projection rebuild (e.g. an idempotency audit) rewrites a fresh
`generated_at`, so local files legitimately diverge from the last-pushed manifest. A
local sha drift means "re-pull to reconcile," not corruption.
**How to apply:** keep the prod check HARD; never "fix" a local sha warning by
weakening the prod check. If you need a clean local snapshot, re-pull rather than
re-pushing rebuilt projections.

# "Published" ≠ "observed running" for a Scheduled Deployment
A successful publish (and a green controlled tick run by hand) does NOT prove the
platform cron actually invoked a scheduled tick.
**Why:** the publish fix and the cron firing are independent. Soak audits kept finding
0 ticks matching the scheduled signature even though publishing worked.
**How to apply:** detect a *real* scheduled run by the tick signature in the ledger
(scheduled deploy bounds: `max_games=20 / max_seconds=900`) AND deployment logs — not
by publish success. Report this honestly as an open operational item; confirm after the
next scheduled window.

# Runbook deploy commands must be pinned verbatim to .replit
The operator-runbook checker (and the test) require the EXACT `.replit` run/build
command strings to appear verbatim (whitespace-normalized) in the runbook.
**Why:** token-subset checks (`"--max-games" in text`) let docs silently drift from
what the deployment actually executes. The architect flagged the weak version.
**How to apply:** compare `" ".join(deployment["run"])` / `["build"]` against
`" ".join(runbook_text.split())`. Update the runbook whenever `.replit` changes.

# Loading a script as a module in tests needs sys.modules registration first
To import a `scripts/*.py` that defines `@dataclass`es via `importlib.util`, set
`sys.modules[spec.name] = mod` BEFORE `spec.loader.exec_module(mod)`.
**Why:** `@dataclass` resolves `cls.__module__` through `sys.modules`; if the module
isn't registered yet it's `None` → `AttributeError: 'NoneType' has no '__dict__'`.
**How to apply:** standard pattern for the pass38 ops tests that import the health
checker script as a module.

# Health checker consumes raw dict events, not Event objects
`run_checks(bundle, ...)` calls `e.get(...)` on events, so synthetic/test bundles must
pass dict events (e.g. `sync.parse_events_text(...)`), not `TournamentLedger().load()`
Event objects. Pool/status helpers, by contrast, take Event objects.
