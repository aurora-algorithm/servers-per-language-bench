#!/usr/bin/env python3
"""The ranking session: eight languages serve the same endpoint on ONE CPU core, flat out, ranked by requests a
second. Reuses session.py (the cores-needed rig): the same endpoint, Postgres on the eight E-cores, oha on two other P-cores,
pinning, quiet gate, byte-identical bodies and 401 checks, oha casts.

Per round (order rotates) and variant, a fresh server process pinned to logical CPU 0 (one physical P-core, its SMT
sibling idle):
  checks   sha256 of four customers' bodies (compared across all variants) and 401 for no token / a forged one
  warm     WARM s flat out (64 connections, no rate), exported and kept so a slow warm-up shows
  measure  WINDOW s flat out; rounds 1..N record oha's live screen, one more plain round runs oha --no-tui

usage (from the repo root):  python tools/rank_session.py RESULTS_DIR [ROUNDS=5]
env:  RANK_VARIANTS (default go,rust,node,python,java,csharp,php,ruby), RANK_WARM_S (20), RANK_WINDOW_S (15),
      BENCH_NO_GATE=1 (pilot)
"""

import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("BENCH_PORT", "8136")
os.environ.setdefault("BENCH_PG_PORT", "5536")
sys.path.insert(0, str(Path(__file__).parent))
import psutil

import session as S
from jwtmint import make_token

WARM_S = int(os.environ.get("RANK_WARM_S", "20"))
WINDOW_S = int(os.environ.get("RANK_WINDOW_S", "15"))
DEFAULT_VARIANTS = "go,rust,node,python,java,csharp,php,ruby"


def time_wait() -> int:
    """Loopback sockets in TIME_WAIT: a stack that opens a connection per request runs Windows out of ports."""
    try:
        return sum(
            1
            for c in psutil.net_connections(kind="tcp")
            if c.status == psutil.CONN_TIME_WAIT
        )
    except psutil.Error:
        return -1


def cell(
    variant: str, secret: str, token: str, pg: S.Postgres, rdir: Path, record: bool
) -> list[dict]:
    server = S.Server(variant, 1, secret, token)
    try:
        shas = S.body_shas(token)
        rows = []
        for kind, seconds, rec in (("warm", WARM_S, False), ("max", WINDOW_S, record)):
            tw_before = time_wait()
            res = S.measure(
                server, pg, f"{variant}-{kind}", token, None, seconds, rdir, rec
            )
            res.update(
                variant=variant,
                cores=1,
                kind=kind,
                ready_s=server.ready_s,
                bodies=shas,
                time_wait_before=tw_before,
                time_wait_after=time_wait(),
            )
            ok = res["ok"] or 1
            res["cpu_us_per_req"] = round(1e6 * res["server_cpu_s"] / ok, 2)
            rows.append(res)
            S.log(
                f"  {variant:12s} {kind:4s} {res['rps']:>9,.0f} req/s  p99 {res['p99_ms']:8.2f} ms  "
                f"cpu {res['server_cpu_pct']:6.1f}%  {res['cpu_us_per_req']:8.1f} us/req  "
                f"pg {res['postgres_tree_cpu_pct']:6.1f}%  rss {res['rss_mb_median']:7.1f} MB  "
                f"non-200 {res['total'] - res['ok']}  tw {res['time_wait_after']}"
            )
        return rows
    finally:
        server.stop()


def lock_versions() -> dict:
    """Library versions of the four added stacks, read from their lock files (what actually ran)."""
    out: dict = {}
    pom = (S.ROOT / "java" / "pom.xml").read_text()
    out["spring_boot"] = re.search(
        r"spring-boot-starter-parent</artifactId>\s*<version>([^<]+)", pom
    ).group(1)
    out["jjwt"] = re.search(r"<jjwt.version>([^<]+)", pom).group(1)
    jar_libs = subprocess.run(
        ["jar", "tf", str(S.ROOT / "java" / "target" / "orders.jar")],
        check=False,
        capture_output=True,
        text=True,
        creationflags=S.NO_WINDOW,
    ).stdout
    out["java_jars"] = sorted(
        re.findall(
            r"BOOT-INF/lib/((?:tomcat-embed-core|HikariCP|postgresql|jackson-databind|"
            r"spring-webmvc|jjwt-impl)[^/]*\.jar)",
            jar_libs,
        )
    )
    csproj = (S.ROOT / "csharp" / "Orders.csproj").read_text()
    out["nuget"] = dict(re.findall(r'Include="([^"]+)" Version="([^"]+)"', csproj))
    lock = json.loads((S.ROOT / "php" / "composer.lock").read_text(encoding="utf-8"))
    out["composer"] = {
        p["name"]: p["version"]
        for p in lock["packages"]
        if p["name"]
        in ("laravel/framework", "firebase/php-jwt", "symfony/http-foundation")
    }
    gemfile_lock = S.ROOT / "ruby" / "Gemfile.lock"
    gems = gemfile_lock.read_text(encoding="utf-8") if gemfile_lock.exists() else ""
    out["gems"] = dict(
        re.findall(
            r"^    (rails|puma|pg|jwt|activerecord|actionpack|rack) \(([^)]+)\)$",
            gems,
            re.MULTILINE,
        )
    )
    return out


def versions() -> dict:
    def cmd(*a: str) -> str:
        try:
            r = subprocess.run(
                a,
                check=False,
                capture_output=True,
                text=True,
                creationflags=S.NO_WINDOW,
            )
            return (r.stdout + r.stderr).strip()
        except OSError as e:
            return f"unavailable: {e}"

    v = S.versions()
    tools = S.ROOT / ".tools"
    nginx = next(tools.glob("nginx-*"))
    v.update(
        {
            "java": cmd(S.JAVA, "-version"),
            "dotnet": cmd("dotnet", "--list-runtimes"),
            "php": cmd(str(tools / "php" / "php-cgi.exe"), "-v"),
            "nginx": cmd(str(nginx / "nginx.exe"), "-v"),
            "ruby": cmd(S.RUBY, "-v"),
            "ruby_yjit": cmd(
                S.RUBY,
                "-e",
                "print defined?(RubyVM::YJIT) ? RubyVM::YJIT.enabled? : 'not built'",
            ),
            "libs": lock_versions(),
        }
    )
    return v


def main() -> int:
    results = Path(sys.argv[1])
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    variants = os.environ.get("RANK_VARIANTS", DEFAULT_VARIANTS).split(",")
    secret = secrets.token_hex(32)
    token = make_token(
        secret,
        {
            "sub": "svc-reports",
            "scope": "orders:read",
            "exp": int(time.time()) + 6 * 3600,
        },
    )
    pg = None
    try:
        results.mkdir(parents=True, exist_ok=False)
        S.SERVER_LOG = results / "server.log"
        (results / "meta.json").write_text(
            json.dumps(
                {
                    "versions": versions(),
                    "rounds": rounds,
                    "variants": variants,
                    "server_cpus": S.CORE_POOL[:1],
                    "oha_cpus": S.OHA_CPUS,
                    "pg_cpus": S.PG_CPUS,
                    "connections": S.CONNECTIONS,
                    "warm_s": WARM_S,
                    "window_s": WINDOW_S,
                    "url": S.URL,
                    "port": S.PORT,
                    "pg_port": S.PG_PORT,
                    "gate": "skipped"
                    if os.environ.get("BENCH_NO_GATE") == "1"
                    else "mean < 5%, max < 15% over 5 s",
                    "started": time.ctime(),
                },
                indent=2,
            )
        )
        pg = S.Postgres(results / "postgres.log")
        S.log("waiting for a quiet machine (up to 4 h)")
        S.quiet_gate(max_wait=4 * 3600)
        for r in range(1, rounds + 2):
            record = r <= rounds
            name = r if record else "plain"
            rdir = results / (f"round{r}" if record else "plain")
            rdir.mkdir()
            S.log(f"round {name} ({'recorded' if record else 'plain'})")
            rows = []
            for variant in S.order_for(r, variants):
                for row in cell(variant, secret, token, pg, rdir, record):
                    row["round"] = name
                    rows.append(row)
                    with open(results / "runs.jsonl", "a") as f:
                        f.write(json.dumps(row) + "\n")
            S.check_bodies(rows)
        S.log("done")
        return 0
    finally:
        if pg:
            pg.stop()


if __name__ == "__main__":
    sys.exit(main())
