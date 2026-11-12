# Servers per language: one API in eight languages under the same traffic

Code and per-run results behind the "How many CPU cores do Go, Rust, Node and Python need for the same traffic?" Short and the "8 languages, one real API request, ranked" Short.

## What is tested
One endpoint, built in every language with its most used web stack. All of them send byte-identical JSON (sha256 of four customers' bodies, compared across all servers every round).

`GET /customers/{id}/orders` with `Authorization: Bearer <JWT>`:
1. verify the HS256 JWT: signature, expiry, scope `orders:read` (401 otherwise; a missing and a forged token are checked to get 401);
2. read the customer's 20 latest orders from Postgres (`db/seed.sql`: 100,000 customers x 20 orders, index on `(customer_id, created_at DESC)`; Postgres formats the timestamp, so every server sends the same bytes);
3. answer `{"customer_id":..,"orders":[..20 rows..]}`.

| | Web stack | JWT library | Postgres access | How it uses its cores |
|---|---|---|---|---|
| Go (`go/`) | Gin 1.12.0, release mode, no logger | golang-jwt v5.3.1 | pgx v5.12.0 pool (32) | `GOMAXPROCS` |
| Rust (`rust/`) | axum 0.8.9 on tokio 1.54.1 | jsonwebtoken 9.3.1 | sqlx 0.8.6 pool (32) | `TOKIO_WORKER_THREADS` |
| JavaScript (`node/`) | Fastify 5.12.8 on Node 24.13.0, `node:cluster` one worker per core | jsonwebtoken 9.0.3 | pg 8.23.1 pool (32 per worker) | `WORKERS` |
| Python (`python/`) | FastAPI 0.121.0 on uvicorn 0.54.0 (httptools), one worker per core | PyJWT 2.10.1 | asyncpg 0.31.0 pool (32 per worker) | `--workers` |
| Java (`java/`) | Spring Boot 4.1.2 (Spring MVC on Tomcat 11.0.27), JDK 25.0.5 | jjwt 0.13.0 | JdbcClient on HikariCP 7.0.2 (32), PostgreSQL JDBC 42.7.14 | the JVM sizes itself from the CPU mask |
| C# (`csharp/`) | ASP.NET Core minimal API on Kestrel, .NET 10.0.14 | Microsoft.IdentityModel.JsonWebTokens 8.23.0 | Npgsql 10.0.3 (pool 32) | .NET sizes itself from the CPU mask |
| PHP (`php/`) | Laravel 13.42.0 on nginx 1.30.6 + 5 php-cgi workers, PHP 8.5.12 with OPcache | firebase/php-jwt 7.2.1 | Laravel `DB::select` (PDO pgsql), a new connection per request | nginx and the 5 workers share the core |
| Ruby (`ruby/`) | Rails 8.1.4.1 (`--api`, production) on Puma 8.0.2, Ruby 4.0.9 | ruby-jwt 3.3.0 | `connection.select_all` (pg gem), Rails' default pool | one process |

Versions are from `results/rank-i7win-20261110/meta.json` (and `results/i7win-20261110/meta.json` for the first four). `php/` and `ruby/` are the stock Laravel and Rails skeletons with our files on top: `app/Http/Controllers/OrdersController.php`, `routes/api.php` and a few lines in `bootstrap/app.php`, `config/app.php`, `config/database.php`; `app/controllers/orders_controller.rb` and `config/routes.rb`. `tools/gen_apps.sh` shows how the skeletons were made.

Two sessions use this endpoint:
- **Cores needed** (`tools/session.py`, Go, Rust, Node, Python): oha sends a fixed 9,500 requests a second, and the API gets more CPU cores until 99 in 100 answers come back in 50 ms or less.
- **Ranking** (`tools/rank_session.py`, all eight): each server on one CPU core, flat out, ranked by requests a second. Two diagnostics ran the same evening: `tools/rank_floor.py` (flat out on `GET /health`: the framework answering "ok", no token, no database, no JSON) and `tools/rank_warmup.py` (a fresh server, twelve back-to-back 5 s flat-out windows).

## Setup
- **Machine:** Intel i7-13700F, RTX 4070 PC, Windows 11 (native, no Docker), Balanced power plan (`meta.json`).
- **Shared versions:** PostgreSQL 18.6, oha 1.16.0, Go 1.27.3, Rust 1.99.1, Node 24.13.0, Python 3.14.10.
- **CPU pinning** (`tools/pin.py`, child processes inherit the mask): Postgres on the eight E-cores (16-23) for the whole session, oha on logical CPUs 12-15. The API gets k P-cores, one logical CPU per physical core (0, 2, 4, ...), SMT siblings idle. The ranking uses CPU 0 only.
- **Postgres:** its own data folder, `shared_buffers=1GB`, `max_connections=400` (`tools/build.sh`, `tools/build_ranking.sh`).
- **Quiet machine:** before every cell the session waits until all 24 logical CPUs average under 5% and none is over 15%.
- **Runs:** 5 recorded rounds (oha's live screen saved as an asciinema cast) and 1 plain round with `--no-tui`. The server order rotates every round.

**Cores needed** (`results/i7win-20261110/meta.json`): 64 connections, a random customer of 10,000-99,999 per request, `oha -q 9500 --latency-correction`, 6 s warm-up then 15 s measured per cell. A cell passes when p99 <= 50 ms, every response is 200 and the delivered rate is at least 98% of the target. k steps up from 1 until a cell passes; round 1 starts every server at k = 1, later rounds one core below the previous answer. At k = 1 each server also runs flat out (no rate) for its requests a second and CPU time per request on one core. The rate was picked from a short pilot by the rule in `tools/pick_rate.py`.

**Ranking** (`results/rank-i7win-20261110/meta.json`): a fresh server on CPU 0 per round and stack, the body and 401 checks, 20 s flat out to warm up (kept as `*-warm.json`), the quiet gate, then 15 s flat out measured at 64 connections.

## Results

**Cores needed for 9,500 requests a second with p99 <= 50 ms** (`results/i7win-20261110/summary.json`, from `answers.jsonl` and `runs.jsonl`)

| Server | Cores needed, rounds 1-5 | Plain round | One core flat out | CPU per request on one core |
|---|---|---|---|---|
| Go + Gin | 1, 1, 1, 1, 1 | 1 | 26,566 req/s | 35.2 µs |
| Rust + axum | 1, 1, 1, 1, 1 | 1 | 19,228 req/s | 48.1 µs |
| Node + Fastify | 3, 3, 2, 2, 4 | 3 | 9,753 req/s | 97.1 µs |
| Python + FastAPI | 4, 4, 4, 4, 4 | 4 | 2,658 req/s | 359.3 µs |

**Ranking: one core, flat out, median of 5 rounds** (`results/rank-i7win-20261110/summary.json`, from `runs.jsonl`)

| # | Server | req/s (min-max) | Plain round | CPU per request | p99 | Memory |
|---|---|---|---|---|---|---|
| 1 | Go + Gin | 26,101 (25,698-26,118) | 25,166 | 37.1 µs | 5.28 ms | 25.3 MB |
| 2 | C# + ASP.NET Core | 21,920 (21,242-24,045) | 22,856 | 43.3 µs | 7.61 ms | 96.2 MB |
| 3 | Java + Spring Boot | 21,627 (21,424-21,809) | 21,465 | 44.7 µs | 9.13 ms | 316.6 MB |
| 4 | Rust + axum | 18,985 (15,986-19,011) | 19,176 | 50.6 µs | 4.60 ms | 12.5 MB |
| 5 | JavaScript + Fastify | 9,792 (9,433-9,927) | 9,740 | 101.5 µs | 9.24 ms | 170.1 MB |
| 6 | Python + FastAPI | 2,660 (2,585-2,708) | 2,631 | 372.9 µs | 25.56 ms | 76.3 MB |
| 7 | Ruby + Rails | 1,395 (1,382-1,441) | 1,400 | 715.8 µs | 93.88 ms | 163.6 MB |
| 8 | PHP + Laravel | 146.5 (144.4-148.5) | 147.5 | 4,544 µs | 643.79 ms | 224.6 MB |

`php-tuned` (Laravel with PDO persistent connections, `DB_PERSISTENT=1`) ran in the same session and is not ranked: 344.5 req/s (340.6-348.8).

With 64 connections flat out, p99 is mostly queueing, so it is not a latency comparison. Memory is the median working set of the server's processes.

**`GET /health` on one core, one run per stack** (`results/floor-i7win-20261110/floor.jsonl`): Rust 123,749, C# 99,536, Go 90,917, JavaScript 55,666, Java 47,002, Python 14,128, Ruby 1,917, PHP 413 requests a second.

**Warm-up** (`results/warmup-i7win-20261110/warmup.jsonl`, twelve 5 s windows from a fresh start): C# went from 6,212 req/s in the first window to 23,322 in the eighth; Java from 1,141 to 20,905 in the third. The curves for all eight stacks are in that file.

## Reproduce
Native Windows, Git Bash, from the repo root. Go, Rust, Node 24, .NET 10 SDK, JDK 25, oha, PostgreSQL 18 binaries, CPython 3.14 for the Python app and a harness Python (3.12 works) with `psutil` and `pywinpty`. `tools/toolchains.sh` fetches portable Maven, PHP + Composer, nginx and Ruby into `.tools/`.

```bash
export PG_BIN=/c/path/to/pgsql-18.6/bin PY314=/c/path/to/Python314/python.exe PY312=/c/path/to/Python312/python.exe
# Cores needed (Go, Rust, Node, Python)
tools/build.sh
BENCH_RATE=9500 BENCH_BAR_MS=50 "$PY312" tools/session.py results/mine 5
python tools/summarize.py cores results/mine
# Ranking (all eight) and its diagnostics
tools/toolchains.sh
tools/build_ranking.sh
source tools/ranking_env.sh
RANK_VARIANTS=go,rust,node,python,java,csharp,php,ruby,php-tuned "$PY312" tools/rank_session.py results/rank-mine 5
tools/rank_diag.sh mine        # writes results/warmup-i7win-mine and results/floor-i7win-mine
python tools/summarize.py rank results/rank-mine
```

`tools/session.py` and `tools/rank_session.py` start and stop Postgres themselves. The JWT secret is random per session and never written to disk.

## Settings worth knowing
- Windows 11, not Linux. uvicorn has no uvloop on Windows, there is no php-fpm (php-cgi workers behind nginx, `tools/php_stack.py`), RubyInstaller's Ruby has no YJIT (`ruby_yjit` in `meta.json`), and Postgres starts a new process per connection.
- Worker processes (Node, Python) share one listening socket and Windows hands out the 64 keep-alive connections, so the spread across workers is whatever `accept()` gives. Per-worker CPU is recorded.
- Every stack runs its stock settings. Nothing tells Java or .NET their core count: the JVM and .NET read the CPU mask and pick Serial GC and workstation GC on one core. PHP's five workers are php-fpm's default `pm.max_children`; Puma's three threads are Rails' default.
- Database pools are 32 for Go, Rust, Node, Python, Java and C#. Rails keeps its default pool of 5. Laravel keeps its default of no persistent connections. Npgsql does not auto-prepare statements; each driver prepares statements its own default way.
- Same bytes: Spring sets `spring.jackson.property-naming-strategy=SNAKE_CASE`; ASP.NET sets a snake_case JSON naming policy; Laravel's API routes drop the `/api` prefix.
- No access logs anywhere (Spring `logging.level.root=WARN`, ASP.NET `LogLevel.Warning`, nginx `access_log off`, `RAILS_LOG_LEVEL=warn`, uvicorn `--no-access-log`, Gin without its logger).
- Laravel runs `php artisan optimize` at start; OPcache is on and the OPcache JIT off, as PHP 8.5 ships. `PHP_FCGI_MAX_REQUESTS=0`. nginx spreads requests with `least_conn` and opens a FastCGI connection per request.
- Tomcat keeps its default of 100 requests per keep-alive connection; sockets left in TIME_WAIT are counted per cell.
- Every stack checks the JWT in its handler with its most used library, with no auth middleware. ASP.NET uses `CreateBuilder` and reflection-based JSON.
