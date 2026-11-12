#!/bin/bash
# Builds the eight servers of the language ranking and the Postgres database (Git Bash on Windows, from the
# repo root). Every cache (Go, Cargo, npm, pip, Maven, NuGet, Composer, Bundler) stays under .cache/ and every
# portable toolchain under .tools/ (tools/toolchains.sh), so deleting the folder removes all of it.
# usage: tools/build_ranking.sh [go rust node python java csharp php ruby db]
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
source tools/ranking_env.sh

go_() { (cd go && go build -trimpath -o api.exe .); }
rust_() { (cd rust && cargo build --release --quiet); }
node_() { (cd node && npm ci --silent --no-audit --no-fund); }
python_() {
  [ -d python/.venv ] || "$PY314" -m venv python/.venv
  python/.venv/Scripts/python.exe -m pip install --quiet --disable-pip-version-check -r python/requirements.txt
}
java_() { (cd java && "$MVN" -B -q -Dmaven.repo.local="$ROOT/.cache/m2" package -DskipTests); }
csharp_() {
  (cd csharp && dotnet publish -c Release -o "$ROOT/csharp/out" -nodeReuse:false --nologo -v quiet)
  dotnet build-server shutdown > /dev/null
}
php_() {
  (cd php && "$PHP" "$COMPOSER" install --no-dev --optimize-autoloader --no-interaction --quiet)
  [ -f php/.env ] || cp php/.env.bench php/.env
  grep -q '^APP_KEY=base64' php/.env || (cd php && "$PHP" artisan key:generate --force --quiet)
}
ruby_() { (cd ruby && "$RUBY_BIN/bundle.bat" install --quiet); }
db_() {
  [ -d pgdata ] && return
  "$PG/initdb.exe" -D pgdata -U bench -A trust -E UTF8 --locale=C > /dev/null
  cat >> pgdata/postgresql.conf <<'CONF'
listen_addresses = '127.0.0.1'
max_connections = 400
shared_buffers = 1GB
logging_collector = off
CONF
  "$PG/pg_ctl.exe" -D pgdata -o "-p $PG_PORT" -w start > /dev/null
  "$PG/createdb.exe" -h 127.0.0.1 -p "$PG_PORT" -U bench orders
  "$PG/psql.exe" -q -h 127.0.0.1 -p "$PG_PORT" -U bench orders -f db/seed.sql
  "$PG/pg_ctl.exe" -D pgdata -w stop -m fast > /dev/null
}

for t in ${@:-go rust node python java csharp php ruby db}; do
  echo "build $t $(date +%T)"
  "${t}_"
done
