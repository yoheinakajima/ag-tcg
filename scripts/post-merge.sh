#!/bin/bash
# Post-merge setup for the PTCG Kaggle project.
# Idempotent, non-interactive, fast. The container's Python environment
# (including kaggle-environments) persists across merges, so this only does a
# lightweight sanity check rather than network installs (pip network is blocked
# in this environment; deps are provisioned out-of-band).
set -e

echo "[post-merge] Python: $(python3 --version 2>&1)"

# Verify the agent module imports cleanly — the single most important invariant
# for a valid Kaggle submission.
python3 -c "import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location('ptcg_main', pathlib.Path('main.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
assert callable(m.agent), 'main.agent is not callable'
print('[post-merge] main.agent imports and is callable')"

echo "[post-merge] OK"
