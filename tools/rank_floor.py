#!/usr/bin/env python3
"""Diagnostic for the ranking: each stack's floor on one core, flat out on GET /health (the framework answering
"ok": no token, no database, no JSON), next to the real endpoint in the same process. The gap between the two is
what the token check, the query and the JSON cost; the floor is what the web stack itself costs.

usage: python tools/rank_floor.py RESULTS_DIR      env: RANK_VARIANTS, RANK_FLOOR_S (10)
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

SECONDS = int(os.environ.get("RANK_FLOOR_S", "10"))
HEALTH_URL = S.BASE + "/health"


def oha_health(seconds: int, export: Path | None) -> list[str]:
    argv = [
        S.OHA,
        "-z",
        f"{seconds}s",
        "-c",
        str(S.CONNECTIONS),
        "--no-tui",
        HEALTH_URL,
    ]
    argv += (
        ["--output-format", "json", "-o", str(export)]
        if export
        else ["--output-format", "quiet"]
    )
    return S.pinned(S.OHA_CPUS, argv)


def floor(variant: str, secret: str, token: str, out: Path) -> dict:
    server = S.Server(variant, 1, secret, token)
    try:
        S.body_shas(token)
        subprocess.check_call(
            oha_health(SECONDS, None),
            stdout=subprocess.DEVNULL,
            creationflags=S.NO_WINDOW,
        )
        S.quiet_gate()
        before = server.sample()
        t0 = time.time()
        export = out / f"{variant}-health.json"
        subprocess.check_call(
            oha_health(SECONDS, export),
            stdout=subprocess.DEVNULL,
            creationflags=S.NO_WINDOW,
        )
        wall = time.time() - t0
        after = server.sample()
        report = json.loads(export.read_text(encoding="utf-8"))
        ok = report["statusCodeDistribution"].get("200", 0)
        cpu = after["cpu_s"] - before["cpu_s"]
        row = {
            "variant": variant,
            "kind": "health",
            "rps": report["summary"]["requestsPerSec"],
            "ok": ok,
            "codes": report["statusCodeDistribution"],
            "server_cpu_pct": round(100 * cpu / wall, 1),
            "cpu_us_per_req": round(1e6 * cpu / max(ok, 1), 2),
            "rss_mb": after["rss_mb"],
        }
        S.log(
            f"  {variant:12s} health {row['rps']:>9,.0f} req/s  {row['cpu_us_per_req']:7.1f} us/req  "
            f"cpu {row['server_cpu_pct']:5.1f}%  codes {row['codes']}"
        )
        return row
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
        with open(out / "floor.jsonl", "w") as f:
            f.writelines(
                json.dumps(floor(v, secret, token, out)) + "\n" for v in variants
            )
    finally:
        pg.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
