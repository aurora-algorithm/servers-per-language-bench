#!/bin/bash
# The diagnostics after the ranking session: warm-up curves, then the /health floor.
# usage: tools/rank_diag.sh SUFFIX
set -uo pipefail
cd "$(dirname "$0")/.."
source tools/ranking_env.sh
"$PY312" tools/rank_warmup.py "results/warmup-i7win-$1"
"$PY312" tools/rank_floor.py "results/floor-i7win-$1"
echo DIAG_DONE
