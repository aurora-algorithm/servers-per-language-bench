#!/usr/bin/env python3
"""Medians over the recorded rounds, written next to the raw rows as summary.json.

usage: python3 tools/summarize.py cores results/i7win-20261110        (tools/session.py)
       python3 tools/summarize.py rank  results/rank-i7win-20261110   (tools/rank_session.py)

cores: per variant, the cores it needed in each round (answers.jsonl) and, from the k = 1 full-speed window, req/s and
CPU time per request (server CPU share / req/s).
rank: per variant, the median req/s of the measured flat-out windows, min and max, the plain round, CPU time per
request and memory; then the GET /health floor (floor-*/floor.jsonl) when it sits next to the session.
"""

import json
import statistics
import sys
from pathlib import Path


def rows_of(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def med(values: list[float]) -> float:
    return round(statistics.median(values), 2)


def cores_summary(session: Path) -> dict:
    rows = rows_of(session / "runs.jsonl")
    answers = [a for a in rows_of(session / "answers.jsonl") if a["round"] != "plain"]
    plain = next(
        (a for a in rows_of(session / "answers.jsonl") if a["round"] == "plain"), None
    )
    out = {}
    for variant in answers[0]["needed"]:
        needed = [a["needed"][variant] for a in answers]
        flat = [
            r
            for r in rows
            if r["variant"] == variant and r["kind"] == "max" and r["round"] != "plain"
        ]
        cpu_us = [r["server_cpu_pct"] / 100 / r["rps"] * 1e6 for r in flat]
        out[variant] = {
            "cores_needed_by_round": needed,
            "cores_needed_plain": plain["needed"][variant] if plain else None,
            "cores_needed_median": statistics.median(needed),
            "k1_flat_out_rps": med([r["rps"] for r in flat]),
            "k1_cpu_us_per_req": med(cpu_us),
        }
    return out


def rank_summary(session: Path) -> dict:
    rows = rows_of(session / "runs.jsonl")
    out = {"ranking": {}}
    for variant in dict.fromkeys(r["variant"] for r in rows):
        rec = [
            r
            for r in rows
            if r["variant"] == variant and r["kind"] == "max" and r["round"] != "plain"
        ]
        plain = next(
            r
            for r in rows
            if r["variant"] == variant and r["kind"] == "max" and r["round"] == "plain"
        )
        rps = [r["rps"] for r in rec]
        out["ranking"][variant] = {
            "rounds": len(rec),
            "rps": med(rps),
            "rps_min": round(min(rps), 2),
            "rps_max": round(max(rps), 2),
            "rps_plain": round(plain["rps"], 2),
            "cpu_us_per_req": med([r["cpu_us_per_req"] for r in rec]),
            "p99_ms": med([r["p99_ms"] for r in rec]),
            "rss_mb": med([r["rss_mb_median"] for r in rec]),
        }
    out["ranking"] = dict(
        sorted(out["ranking"].items(), key=lambda kv: kv[1]["rps"], reverse=True)
    )
    suffix = session.name.removeprefix("rank-")
    floor = session.parent / f"floor-{suffix}" / "floor.jsonl"
    if floor.exists():
        out["health_floor"] = {
            r["variant"]: {"rps": round(r["rps"], 2)} for r in rows_of(floor)
        }
    return out


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("cores", "rank"):
        sys.exit(__doc__)
    session = Path(sys.argv[2])
    summary = (
        cores_summary(session) if sys.argv[1] == "cores" else rank_summary(session)
    )
    (session / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
