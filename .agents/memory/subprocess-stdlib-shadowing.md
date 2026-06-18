---
name: Subprocess script-dir stdlib shadowing
description: Why per-game child subprocesses crashed with "attempted relative import with no known parent package", and the sys.path fix.
---

# Child subprocess must strip its own dir from sys.path

When a module *inside the package* is spawned as a standalone script
(`python .../experiments/_game_subprocess.py`), Python puts that file's
directory on `sys.path[0]`. If the package dir contains files whose names
collide with the stdlib — here `experiments/queue.py` shadows stdlib `queue` —
then any deep `import queue` (threading, multiprocessing, cabt/OpenSpiel
internals) loads OUR package file as a *top-level* module. Its `from .config
import ...` then raises `ImportError("attempted relative import with no known
parent package")`.

Symptom: the per-game subprocess runner reported every game as a crash
(`crashes=N`, `completed=false`, error string above), while the *in-process*
smoke test and a plain throwaway subprocess both imported fine. The tell is that
the failure is an import error on a stdlib name surfacing as a *relative* import
error — that only happens under name shadowing.

**Fix:** in the child entry-point, remove the script's own directory (and `""`/
`"."`) from `sys.path`, then add the real package root (`.../src`). This keeps
`ptcg_activegraph` importable while leaving the stdlib unshadowed.

**Why it matters:** without this, the entire two-stage cabt eval silently
produces all-crash metrics that look like real (terrible) results. Any new
standalone child script under a package dir that has stdlib-colliding filenames
(`queue.py`, `types.py`, `select.py`, `token.py`, etc.) needs the same guard.
