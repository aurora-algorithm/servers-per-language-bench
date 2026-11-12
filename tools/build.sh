#!/bin/bash
# Builds the four servers of the cores-needed session (Go, Rust, Node, Python) and the Postgres database
# (Git Bash on Windows, from the repo root). Set PG_BIN (PostgreSQL 18 bin folder) and PY314 (a CPython 3.14
# python.exe); go, cargo and node must be on PATH.
set -euo pipefail
cd "$(dirname "$0")/.."
PG=${PG_BIN:?set PG_BIN to the PostgreSQL 18 bin folder}
PY314=${PY314:?set PY314 to a CPython 3.14 python.exe}
(cd go && go build -trimpath -o api.exe .)
(cd rust && cargo build --release --quiet)
(cd node && npm ci --silent --no-audit --no-fund)
[ -d python/.venv ] || "$PY314" -m venv python/.venv
python/.venv/Scripts/python.exe -m pip install --quiet --disable-pip-version-check -r python/requirements.txt
if [ ! -d pgdata ]; then
  "$PG/initdb.exe" -D pgdata -U bench -A trust -E UTF8 --locale=C > /dev/null
  cat >> pgdata/postgresql.conf <<'CONF'
listen_addresses = '127.0.0.1'
max_connections = 400
shared_buffers = 1GB
logging_collector = off
CONF
  "$PG/pg_ctl.exe" -D pgdata -o "-p 5547" -w start > /dev/null
  "$PG/createdb.exe" -h 127.0.0.1 -p 5547 -U bench orders
  "$PG/psql.exe" -q -h 127.0.0.1 -p 5547 -U bench orders -f db/seed.sql
  "$PG/pg_ctl.exe" -D pgdata -w stop -m fast > /dev/null
fi
ls -l go/api.exe rust/target/release/api.exe
