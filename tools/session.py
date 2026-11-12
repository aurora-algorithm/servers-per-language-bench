#!/usr/bin/env python3
"""The cores-needed session, natively on Windows (i7-13700F): how many CPU cores does each language need
to serve the same traffic with p99 under a bar?

One endpoint in four languages (GET /customers/{id}/orders: verify an HS256 JWT, read that customer's 20 latest orders
from Postgres, answer JSON). Per round and variant (order rotates every round) the server is started on k performance
cores (one logical CPU per physical core, SMT siblings idle) and oha sends a fixed rate at it:

  warm    8 s at the target rate
  cell   20 s at the target rate, open loop (oha -q RATE --latency-correction), p99 read from oha's JSON
  max    (k = 1 only) 10 s at full speed, 64 connections: what one core does flat out

k steps up from 1 until the cell passes (p99 <= BAR_MS, every response 200, achieved rate >= 98% of the target).
Round 1 starts every variant at k = 1; later rounds start one core below the previous round's answer, so the failing
count under the answer is measured again every round.

Postgres 18 runs on the eight E-cores for the whole session; oha on two other P-cores. Rounds 1..N record oha's live
screen (tools/cast.py, an asciinema cast); one more round runs oha with --no-tui to check that the recording didn't
move the numbers. Response bodies are sha256-compared across all variants (byte identical); a mismatch stops it.

usage (from the repo root):  python tools/session.py RESULTS_DIR [ROUNDS=5]
env:  BENCH_RATE (default 6000), BENCH_BAR_MS (default 50), BENCH_SECONDS_SCALE (pilot: 0.5), BENCH_NO_GATE=1 (pilot),
      BENCH_VARIANTS=go,rust,node,python, BENCH_MAX_CORES (default 6), PG_BIN, OHA, NODE, JAVA, RUBY, APP_PY
"""

import hashlib
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).parent))
from jwtmint import make_token

CORE_POOL = [0, 2, 4, 6, 8, 10]  # P-cores, one logical CPU per physical core
OHA_CPUS = [12, 13, 14, 15]  # two other physical P-cores
PG_CPUS = list(range(16, 24))  # the eight E-cores
QUIET_CPUS = list(range(24))
PORT = int(os.environ.get("BENCH_PORT", "8127"))
PG_PORT = int(os.environ.get("BENCH_PG_PORT", "5547"))
BASE = f"http://127.0.0.1:{PORT}"
DATABASE_URL = f"postgres://bench@127.0.0.1:{PG_PORT}/orders"
CONNECTIONS = 64
RATE = int(os.environ.get("BENCH_RATE", "6000"))
BAR_MS = float(os.environ.get("BENCH_BAR_MS", "50"))
MAX_CORES = int(os.environ.get("BENCH_MAX_CORES", str(len(CORE_POOL))))
SCALE = float(os.environ.get("BENCH_SECONDS_SCALE", "1"))
WARM_S = int(os.environ.get("BENCH_WARM_S", "6"))
WINDOW_S = int(os.environ.get("BENCH_WINDOW_S", "15"))
COLS, ROWS = (
    64,
    14,
)  # oha's live screen at a size that stays readable on a phone (100 and 110 used the same)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PY = (
    str(Path(sys.executable).with_name("python.exe"))
    if os.name == "nt"
    else sys.executable
)
TOOLS = Path(__file__).parent
ROOT = TOOLS.parent
OHA = os.environ.get("OHA") or shutil.which("oha") or "oha"
PG_BIN = Path(os.environ.get("PG_BIN", "C:/pgsql-18.6/bin"))
PG_DATA = Path(os.environ.get("PG_DATA", ROOT / "pgdata"))
EXE = ".exe" if os.name == "nt" else ""
APP_PY = os.environ.get("APP_PY") or str(
    ROOT
    / "python"
    / ".venv"
    / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
)
NODE = os.environ.get("NODE") or shutil.which("node") or "node"
JAVA = os.environ.get("JAVA") or shutil.which("java") or "java"
RUBY = os.environ.get("RUBY") or str(ROOT / ".tools" / "ruby" / "bin" / f"ruby{EXE}")
SESSION_KEY_BASE = secrets.token_hex(
    64
)  # Rails refuses to boot in production without one; never written anywhere
URL = (
    BASE + "/customers/[1-9][0-9]{4}/orders"
)  # customers 10,000..99,999 of 100,000, uniform
CHECK_IDS = [1, 777, 54321, 100000]
SERVER_LOG = ROOT / "results" / "server.log"


def argv_for(variant: str, k: int) -> tuple[list[str], dict]:
    """The server command and its environment for k cores. Every runtime is told k explicitly."""
    lang, _, persistent = variant.partition("-")
    env = {"PORT": str(PORT), "DATABASE_URL": DATABASE_URL}
    if lang == "go":
        env["GOMAXPROCS"] = str(k)
        return [str(ROOT / "go" / f"api{EXE}")], env
    if lang == "rust":
        env["TOKIO_WORKER_THREADS"] = str(k)
        return [str(ROOT / "rust" / "target" / "release" / f"api{EXE}")], env
    if lang == "node":
        env["WORKERS"] = str(k)
        env["UV_THREADPOOL_SIZE"] = "4"
        return [NODE, str(ROOT / "node" / "server.js")], env
    if lang == "python":
        return [
            APP_PY,
            "-m",
            "uvicorn",
            "app:app",
            "--app-dir",
            str(ROOT / "python"),
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--workers",
            str(k),
            "--log-level",
            "warning",
            "--no-access-log",
        ], env
    # The ranking's other four (one core only): the JVM, .NET and Ruby size themselves from the pinned mask; PHP runs
    # php-fpm's default pool of five php-cgi workers behind nginx (tools/php_stack.py), whatever k is.
    if lang == "java":
        env["DB_URL"] = f"jdbc:postgresql://127.0.0.1:{PG_PORT}/orders"
        return [JAVA, "-jar", str(ROOT / "java" / "target" / "orders.jar")], env
    if lang == "csharp":
        env["DB_CONN"] = (
            f"Host=127.0.0.1;Port={PG_PORT};Username=bench;Database=orders;Maximum Pool Size=32"
        )
        return [str(ROOT / "csharp" / "out" / f"Orders{EXE}")], env
    if lang == "php":
        if persistent:  # php-tuned: PDO persistent connections
            env["DB_PERSISTENT"] = "1"
        return [PY, str(TOOLS / "php_stack.py"), str(PORT)], env
    if lang == "ruby":
        env["RAILS_LOG_LEVEL"] = "warn"
        env["SECRET_KEY_BASE"] = SESSION_KEY_BASE
        return [
            RUBY,
            str(ROOT / "ruby" / "bin" / "rails"),
            "server",
            "-e",
            "production",
            "-b",
            "127.0.0.1",
            "-p",
            str(PORT),
        ], env
    raise ValueError(variant)


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def secs(s: float) -> int:
    return max(2, round(s * SCALE))


def quiet_gate(max_wait: int = 1800) -> dict:
    """Waits until the whole machine is idle (mean of all cores under 5%, none over 15%, over 5 s); returns that
    reading. Gives up after max_wait: a busy machine (another program or benchmark) voids the numbers."""
    if os.environ.get("BENCH_NO_GATE") == "1":
        return {"gate": "skipped"}
    waited = 0
    while True:
        per = psutil.cpu_percent(interval=5, percpu=True)
        ours = [per[c] for c in QUIET_CPUS]
        reading = {
            "cores_mean": round(sum(ours) / len(ours), 1),
            "cores_max": max(ours),
        }
        if reading["cores_mean"] < 5 and reading["cores_max"] < 15:
            return reading
        if waited >= max_wait:
            raise RuntimeError(f"machine stayed busy for {max_wait} s: {reading}")
        if waited % 300 == 0:
            log(f"machine busy {reading}, waiting")
        waited += 5


def http(path: str, token: str | None, timeout: float = 5) -> tuple[int, bytes]:
    req = urllib.request.Request(
        BASE + path, headers={"Authorization": f"Bearer {token}"} if token else {}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def pinned(cpus: list[int], argv: list[str]) -> list[str]:
    return [PY, str(TOOLS / "pin.py"), ",".join(map(str, cpus)), *argv]


def launcher(p: psutil.Process) -> bool:
    """tools/php_stack.py only starts nginx and php-cgi and then sleeps; it is not counted as the server."""
    try:
        return any(a.endswith("php_stack.py") for a in p.cmdline())
    except psutil.Error:
        return False


def tree(pid: int) -> list[psutil.Process]:
    try:
        root = psutil.Process(pid)
        return [root, *root.children(recursive=True)]
    except psutil.NoSuchProcess:
        return []


class Postgres:
    """Postgres pinned to the E-cores for the whole session; backends inherit the postmaster's mask. Started through
    pg_ctl: postgres.exe refuses to run under an administrator account, pg_ctl drops the rights first."""

    def __init__(self, log: Path):
        argv = [
            str(PG_BIN / f"pg_ctl{EXE}"),
            "-D",
            str(PG_DATA),
            "-o",
            f"-p {PG_PORT}",
            "-l",
            str(log),
            "-w",
            "-t",
            "120",
            "start",
        ]
        subprocess.check_call(
            pinned(PG_CPUS, argv), stdout=subprocess.DEVNULL, creationflags=NO_WINDOW
        )
        pid = int((PG_DATA / "postmaster.pid").read_text().split()[0])
        self.postmaster = psutil.Process(pid)
        for p in self.procs():
            p.cpu_affinity(PG_CPUS)

    def procs(self) -> list[psutil.Process]:
        try:
            return [self.postmaster, *self.postmaster.children(recursive=True)]
        except psutil.NoSuchProcess:
            return []

    def cpu_seconds(self) -> float:
        total = 0.0
        for p in self.procs():
            try:
                t = p.cpu_times()
                total += t.user + t.system
            except psutil.NoSuchProcess:
                pass
        return total

    def stop(self) -> None:
        subprocess.call(
            [
                str(PG_BIN / f"pg_ctl{EXE}"),
                "-D",
                str(PG_DATA),
                "stop",
                "-m",
                "fast",
                "-w",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW,
        )


class Server:
    """One API (a process tree: uvicorn and node:cluster run one worker per core) pinned to its k cores from the
    first instruction; pin.py sets the mask and every child inherits it."""

    def __init__(self, variant: str, k: int, secret: str, token: str):
        argv, extra = argv_for(variant, k)
        env = dict(os.environ, JWT_SECRET=secret, **extra)
        self.cpus = CORE_POOL[:k]
        t0 = time.time()
        with open(SERVER_LOG, "a") as out:
            out.write(f"--- {time.ctime()} {variant} k={k}\n")
            out.flush()
            self.wrapper = subprocess.Popen(
                pinned(self.cpus, argv),
                env=env,
                cwd=str(ROOT),
                stdout=out,
                stderr=subprocess.STDOUT,
                creationflags=NO_WINDOW,
            )
        try:
            self.ready_s = self._wait_ready(t0, token)
        except RuntimeError:
            self.stop()
            raise
        time.sleep(2)  # the other workers of a multi-process server finish starting

    def _wait_ready(self, t0: float, token: str) -> float:
        last = None
        while time.time() < t0 + 120:
            if self.wrapper.poll() is not None:
                raise RuntimeError(f"server exited with {self.wrapper.returncode}")
            try:
                status = http("/customers/1/orders", token, 1)[0]
                if status == 200:
                    return round(time.time() - t0, 2)
                last = status
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                pass
            time.sleep(0.1)
        raise RuntimeError(
            f"server not ready after 120 s (last status {last}, see {SERVER_LOG})"
        )

    def procs(self) -> list[psutil.Process]:
        return [
            p
            for p in tree(self.wrapper.pid)[1:]
            if p.name().lower() not in ("conhost.exe",) and not launcher(p)
        ]

    def sample(self) -> dict:
        rss, cpu, workers = 0, 0.0, 0
        for p in self.procs():
            try:
                rss += p.memory_info().rss
                t = p.cpu_times()
                cpu += t.user + t.system
                workers += 1
            except psutil.NoSuchProcess:
                pass
        return {
            "rss_mb": round(rss / 2**20, 1),
            "cpu_s": round(cpu, 3),
            "procs": workers,
        }

    def worker_cpu(self) -> list[float]:
        out = []
        for p in self.procs():
            try:
                t = p.cpu_times()
                out.append(round(t.user + t.system, 3))
            except psutil.NoSuchProcess:
                pass
        return out

    def stop(self) -> None:
        procs = tree(self.wrapper.pid)
        for p in procs:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(procs, timeout=30)
        for _ in range(
            100
        ):  # the port must be free, or the next server's check would answer from this one
            try:
                http("/health", None, 0.5)
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                return
            time.sleep(0.1)
        raise RuntimeError("old server still answers after stop")


def oha_argv(
    token: str, seconds: int, rate: int | None, export: Path | None, tui: bool
) -> list[str]:
    argv = [
        OHA,
        "-z",
        f"{seconds}s",
        "-c",
        str(CONNECTIONS),
        "-H",
        f"Authorization: Bearer {token}",
        "--rand-regex-url",
        URL,
    ]
    if rate:
        argv += ["-q", str(rate), "--latency-correction"]
    argv += (
        ["--output-format", "json", "-o", str(export)]
        if export
        else ["--output-format", "quiet"]
    )
    if not tui:
        argv.append("--no-tui")
    return pinned(OHA_CPUS, argv)


def sample_loop(server: Server, stop: threading.Event, out: list) -> None:
    while not stop.wait(0.5):
        out.append(server.sample())


def measure(
    server: Server,
    pg: Postgres,
    cell: str,
    token: str,
    rate: int | None,
    seconds: int,
    rdir: Path,
    record: bool,
) -> dict:
    export = rdir / f"{cell}.json"
    argv = oha_argv(token, seconds, rate, export, record)
    busy = quiet_gate()
    samples: list = []
    stop = threading.Event()
    sampler = threading.Thread(target=sample_loop, args=(server, stop, samples))
    before, pg_before, w_before = server.sample(), pg.cpu_seconds(), server.worker_cpu()
    psutil.cpu_percent(percpu=True)
    sampler.start()
    t0 = time.time()
    try:
        if record:
            rc = subprocess.call(
                [
                    PY,
                    str(TOOLS / "cast.py"),
                    str(rdir / f"{cell}.cast"),
                    str(COLS),
                    str(ROWS),
                    "--",
                    *argv,
                ],
                creationflags=NO_WINDOW,
            )
        else:
            rc = subprocess.call(
                argv, stdout=subprocess.DEVNULL, creationflags=NO_WINDOW
            )
    finally:
        stop.set()
        sampler.join()
    wall = time.time() - t0
    cpu_during = psutil.cpu_percent(percpu=True)
    after, pg_after, w_after = server.sample(), pg.cpu_seconds(), server.worker_cpu()
    if rc != 0 or not export.exists():
        raise RuntimeError(f"{cell}: oha failed ({rc})")
    report = json.loads(export.read_text(encoding="utf-8"))
    codes = report.get("statusCodeDistribution", {})
    pct = report["latencyPercentiles"]
    ok = codes.get("200", 0)
    # oha cancels the requests still in flight when the window closes; those are not server errors.
    errors = {
        e: n
        for e, n in report.get("errorDistribution", {}).items()
        if e != "aborted due to deadline"
    }
    total = sum(codes.values()) + sum(errors.values())
    rss = sorted(s["rss_mb"] for s in samples) or [after["rss_mb"]]
    p99 = (pct["p99"] or 0) * 1000
    res = {
        "cell": cell,
        "started": t0,
        "seconds": seconds,
        "rate": rate,
        "bar_ms": BAR_MS,
        "busy_before": busy,
        "rps": report["summary"]["requestsPerSec"],
        "ok": ok,
        "total": total,
        "codes": codes,
        "errors": errors,
        "aborted_at_deadline": report.get("errorDistribution", {}).get(
            "aborted due to deadline", 0
        ),
        "p50_ms": (pct["p50"] or 0) * 1000,
        "p90_ms": (pct["p90"] or 0) * 1000,
        "p99_ms": p99,
        "p999_ms": (pct["p99.9"] or 0) * 1000,
        "max_ms": (report["summary"]["slowest"] or 0) * 1000,
        "server_cpu_pct": round(100 * (after["cpu_s"] - before["cpu_s"]) / wall, 1),
        "server_cpu_s": round(after["cpu_s"] - before["cpu_s"], 3),
        "wall_s": round(wall, 3),
        "postgres_cpu_pct": round(
            sum(cpu_during[c] for c in PG_CPUS if c < len(cpu_during)), 1
        ),
        "postgres_tree_cpu_pct": round(100 * (pg_after - pg_before) / wall, 1),
        "worker_cpu_s": [round(a - b, 2) for a, b in zip(w_after, w_before)]
        if len(w_after) == len(w_before)
        else [],
        "rss_mb_median": rss[len(rss) // 2],
        "rss_mb_max": rss[-1],
        "procs": after["procs"],
        "cpu_percpu_during": cpu_during,
    }
    if rate:
        res["pass"] = bool(
            ok == total and total > 0 and res["rps"] >= 0.98 * rate and p99 <= BAR_MS
        )
    return res


def body_shas(token: str) -> dict:
    out = {}
    for cid in CHECK_IDS:
        status, body = http(f"/customers/{cid}/orders", token)
        if status != 200:
            raise RuntimeError(f"/customers/{cid}/orders answered {status}")
        out[str(cid)] = hashlib.sha256(body).hexdigest()
    bad = {
        "no token": http("/customers/1/orders", None)[0],
        "bad signature": http("/customers/1/orders", token[:-2] + "xx")[0],
    }
    if set(bad.values()) != {401}:
        raise RuntimeError(f"auth check failed: {bad}")
    return out


def run_cell(
    variant: str,
    k: int,
    secret: str,
    token: str,
    pg: Postgres,
    rdir: Path,
    record: bool,
    with_rate: bool = True,
    with_max: bool = False,
) -> list[dict]:
    rows = []
    server = Server(variant, k, secret, token)
    try:
        shas = body_shas(token)
        subprocess.check_call(
            oha_argv(token, secs(WARM_S), RATE, None, False),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW,
        )
        if with_rate:
            res = measure(
                server, pg, f"{variant}-k{k}", token, RATE, secs(WINDOW_S), rdir, record
            )
            res.update(
                variant=variant,
                cores=k,
                kind="rate",
                ready_s=server.ready_s,
                bodies=shas,
            )
            rows.append(res)
            log(
                f"  {variant:14s} k={k}  {res['rps']:>8,.0f} req/s  p99 {res['p99_ms']:9.2f} ms  "
                f"cpu {res['server_cpu_pct']:6.1f}%  pg {res['postgres_cpu_pct']:6.1f}%  "
                f"rss {res['rss_mb_median']:7.1f} MB  {'PASS' if res['pass'] else 'fail'}"
            )
        if with_max:
            res = measure(
                server, pg, f"{variant}-k{k}-max", token, None, secs(10), rdir, record
            )
            res.update(
                variant=variant,
                cores=k,
                kind="max",
                ready_s=server.ready_s,
                bodies=shas,
            )
            rows.append(res)
            log(
                f"  {variant:14s} k={k}  max {res['rps']:>8,.0f} req/s  p99 {res['p99_ms']:8.2f} ms  "
                f"cpu {res['server_cpu_pct']:6.1f}%  pg {res['postgres_cpu_pct']:6.1f}%"
            )
    finally:
        server.stop()
    return rows


def step_variant(
    variant: str,
    start: int,
    secret: str,
    token: str,
    pg: Postgres,
    rdir: Path,
    record: bool,
) -> tuple[list[dict], int | None]:
    rows, needed = [], None
    if start > 1:  # what one core does flat out, measured every round
        rows += run_cell(
            variant, 1, secret, token, pg, rdir, record, with_rate=False, with_max=True
        )
    for k in range(start, MAX_CORES + 1):
        cell = run_cell(variant, k, secret, token, pg, rdir, record, with_max=(k == 1))
        rows += cell
        if cell[0]["pass"]:
            needed = k
            break
    if (
        start > 1 and needed == start
    ):  # the count under the answer must fail in this round too
        rows += run_cell(variant, start - 1, secret, token, pg, rdir, record)
        if rows[-1]["pass"]:
            needed = (
                None  # passed lower than expected: step down from scratch next round
            )
    return rows, needed


def order_for(round_no: int, items: list[str]) -> list[str]:
    k = (round_no - 1) % len(items)
    return items[k:] + items[:k]


def check_bodies(rows: list[dict]) -> None:
    seen = {json.dumps(r["bodies"], sort_keys=True) for r in rows if "bodies" in r}
    if len(seen) > 1:
        raise RuntimeError(f"response bodies differ between variants: {seen}")


def versions() -> dict:
    def cmd(*a: str) -> str:
        try:
            return subprocess.run(
                a, check=False, capture_output=True, text=True, creationflags=NO_WINDOW
            ).stdout.strip()
        except OSError as e:
            return f"unavailable: {e}"

    def gomod() -> dict:
        mods = {}
        for line in (ROOT / "go" / "go.mod").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] in (
                "github.com/gin-gonic/gin",
                "github.com/golang-jwt/jwt/v5",
                "github.com/jackc/pgx/v5",
            ):
                mods[parts[0]] = parts[1]
        return mods

    def crates() -> dict:
        lock = (
            (ROOT / "rust" / "Cargo.lock").read_text()
            if (ROOT / "rust" / "Cargo.lock").exists()
            else ""
        )
        out = {}
        for block in lock.split("[[package]]"):
            lines = dict(
                l.split(" = ", 1) for l in block.strip().splitlines() if " = " in l
            )
            name = lines.get("name", "").strip('"')
            if name in ("axum", "tokio", "sqlx", "jsonwebtoken", "serde_json", "hyper"):
                out[name] = lines.get("version", "").strip('"')
        return out

    def npm() -> dict:
        out = {}
        for name in ("fastify", "jsonwebtoken", "pg"):
            p = ROOT / "node" / "node_modules" / name / "package.json"
            out[name] = (
                json.loads(p.read_text())["version"] if p.exists() else "missing"
            )
        return out

    return {
        "go": cmd("go", "version"),
        "go_mods": gomod(),
        "rustc": cmd("rustc", "-vV"),
        "crates": crates(),
        "node": cmd(NODE, "--version"),
        "npm": npm(),
        "python": cmd(APP_PY, "--version"),
        "pip": cmd(APP_PY, "-m", "pip", "freeze"),
        "postgres": cmd(str(PG_BIN / f"postgres{EXE}"), "--version"),
        "oha": cmd(OHA, "--version"),
        "os": platform.platform(),
        "cpu": platform.processor(),
        "power_plan": cmd("powercfg", "/getactivescheme") if os.name == "nt" else "",
    }


def main() -> int:
    results = Path(sys.argv[1])
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    variants = os.environ.get("BENCH_VARIANTS", "go,rust,node,python").split(",")
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
        global SERVER_LOG
        SERVER_LOG = results / "server.log"
        (results / "meta.json").write_text(
            json.dumps(
                {
                    "versions": versions(),
                    "rounds": rounds,
                    "variants": variants,
                    "core_pool": CORE_POOL,
                    "oha_cpus": OHA_CPUS,
                    "pg_cpus": PG_CPUS,
                    "connections": CONNECTIONS,
                    "rate": RATE,
                    "bar_ms": BAR_MS,
                    "max_cores": MAX_CORES,
                    "seconds_scale": SCALE,
                    "warm_s": WARM_S,
                    "window_s": WINDOW_S,
                    "url": URL,
                    "started": time.ctime(),
                },
                indent=2,
            )
        )
        pg = Postgres(results / "postgres.log")
        log("waiting for a quiet machine (up to 4 h)")
        quiet_gate(max_wait=4 * 3600)
        start = {v: 1 for v in variants}
        for r in range(1, rounds + 2):
            record = r <= rounds
            rdir = results / (f"round{r}" if record else "plain")
            rdir.mkdir()
            log(f"round {r} ({'recorded' if record else 'plain'})")
            rows, answers = [], {}
            for variant in order_for(r, variants):
                vrows, needed = step_variant(
                    variant, start[variant], secret, token, pg, rdir, record
                )
                rows += vrows
                answers[variant] = needed
                start[variant] = max(1, needed - 1) if needed else 1
            check_bodies(rows)
            log(f"round {r} cores needed: {answers}")
            with open(results / "runs.jsonl", "a") as f:
                for row in rows:
                    row["round"] = r if record else "plain"
                    f.write(json.dumps(row) + "\n")
            with open(results / "answers.jsonl", "a") as f:
                f.write(
                    json.dumps({"round": r if record else "plain", "needed": answers})
                    + "\n"
                )
        log("done")
        return 0
    finally:
        if pg:
            pg.stop()


if __name__ == "__main__":
    sys.exit(main())
