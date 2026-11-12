#!/usr/bin/env python3
"""Picks the session's fixed rate from a pilot's one-core flat-out runs (the max cells at k = 1), by a rule written
down before the full session: the fastest language should hold it on one core with room to spare (60% of its
one-core maximum) and the slowest should fit in the cores we have (75% of five of its cores). Rounded down to 500.

usage: python tools/pick_rate.py results/<pilot>      prints the rate
"""
import json
import statistics
import sys
from pathlib import Path

LANGS = ("go", "rust", "node", "python")


def main() -> int:
    rows = [json.loads(l) for l in (Path(sys.argv[1]) / "runs.jsonl").read_text().splitlines() if l.strip()]
    best = {}
    for lang in LANGS:
        vals = [r["rps"] for r in rows if r["variant"] == lang and r["kind"] == "max" and r["cores"] == 1]
        if not vals:
            sys.exit(f"no one-core max run for {lang}")
        best[lang] = statistics.median(vals)
    rate = min(0.6 * max(best.values()), 0.75 * 5 * min(best.values()))
    rate = max(500, int(rate // 500 * 500))
    print(json.dumps({"one_core_max": {k: round(v) for k, v in best.items()}, "rate": rate}), file=sys.stderr)
    print(rate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
