#!/usr/bin/env python3
"""Diagnostic for the ranking: how long each stack takes to reach its speed on one core. A fresh server, then
back-to-back flat-out windows of STEP seconds (64 connections, no rate) for TOTAL seconds; requests a second and
server CPU per window. Shows whether the session's 20 s warm-up was enough (the JIT runtimes tier up under load).

usage: python tools/rank_warmup.py RESULTS_DIR      env: RANK_VARIANTS, RANK_STEP_S (5), RANK_TOTAL_S (60)
"""

import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("BENCH_PORT", "8136")
os.environ.setdefault("BENCH_PG_PORT", "5536")
sys.path.insert(0, str(Path(__file__).parent))
import session as S
from jwtmint import make_token

STEP_S = int(os.environ.get("RANK_STEP_S", "5"))
TOTAL_S = int(os.environ.get("RANK_TOTAL_S", "60"))


def curve(variant: str, secret: str, token: str, out: Path) -> dict:
    S.quiet_gate()
    server = S.Server(variant, 1, secret, token)
    try:
        S.body_shas(token)
        t_start = time.time()
        points = []
        for i in range(TOTAL_S // STEP_S):
            export = out / f"{variant}-{i:02d}.json"
            before = server.sample()
            t0 = time.time()
            subprocess.check_call(
                S.oha_argv(token, STEP_S, None, export, False),
                stdout=subprocess.DEVNULL,
                creationflags=S.NO_WINDOW,
            )
            wall = time.time() - t0
            after = server.sample()
            report = json.loads(export.read_text(encoding="utf-8"))
            points.append(
                {
                    "t_end_s": round(time.time() - t_start, 2),
                    "rps": report["summary"]["requestsPerSec"],
                    "ok": report["statusCodeDistribution"].get("200", 0),
                    "server_cpu_pct": round(
                        100 * (after["cpu_s"] - before["cpu_s"]) / wall, 1
                    ),
                    "rss_mb": after["rss_mb"],
                }
            )
        S.log(f"  {variant:12s} " + " ".join(f"{p['rps']:>7,.0f}" for p in points))
        return {
            "variant": variant,
            "step_s": STEP_S,
            "ready_s": server.ready_s,
            "points": points,
        }
    finally:
        server.stop()


def main() -> int:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=False)
    S.SERVER_LOG = out / "server.log"
    variants = os.environ.get(
        "RANK_VARIANTS", "go,rust,node,python,java,csharp,php,ruby"
    ).split(",")
    secret = secrets.token_hex(32)
    token = make_token(
        secret,
        {"sub": "svc-reports", "scope": "orders:read", "exp": int(time.time()) + 3600},
    )
    pg = S.Postgres(out / "postgres.log")
    try:
        S.quiet_gate(max_wait=3600)
        with open(out / "warmup.jsonl", "w") as f:
            f.writelines(
                json.dumps(curve(v, secret, token, out)) + "\n" for v in variants
            )
    finally:
        pg.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
