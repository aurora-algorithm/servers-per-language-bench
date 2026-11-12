# Sourced by the ranking scripts (Git Bash on Windows): toolchains on PATH, every cache inside the repo folder.
# Set PG_BIN, PY314 and PY312 (or edit the defaults below); Go, Rust, Node, .NET 10 and JDK 25 must be installed.
ROOT="${ROOT:-$PWD}"
T="$ROOT/.tools"
C="$ROOT/.cache"
mkdir -p "$C"
export JAVA_HOME="${JAVA_HOME:-/c/Program Files/Eclipse Adoptium/jdk-25.0.5.8-hotspot}"
export PATH="/c/Program Files/Go/bin:$HOME/.cargo/bin:/c/Program Files/nodejs:/c/Program Files/dotnet:$JAVA_HOME/bin:$PATH"
export GOCACHE="$C/go-build" GOMODCACHE="$C/go-mod" GOPATH="$C/gopath" GOTELEMETRY=off
export CARGO_HOME="$C/cargo"
export npm_config_cache="$C/npm"
export PIP_CACHE_DIR="$C/pip"
export NUGET_PACKAGES="$C/nuget" DOTNET_CLI_HOME="$C/dotnet" DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 \
  DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 MSBUILDDISABLENODEREUSE=1
export COMPOSER_HOME="$C/composer" COMPOSER_CACHE_DIR="$C/composer-cache"
export BUNDLE_PATH="$C/bundle" BUNDLE_USER_HOME="$C/bundle-home" GEM_HOME="$C/gems" GEM_SPEC_CACHE="$C/gem-specs"
MVN="$T/apache-maven-3.9.11/bin/mvn"
PHP="$T/php/php.exe"
COMPOSER="$T/php/composer.phar"
RUBY_BIN="$T/ruby/bin"
PG="${PG_BIN:-/c/pgsql-18.6/bin}"
PG_PORT=5536
PY314="${PY314:-$LOCALAPPDATA/Programs/Python/Python314/python.exe}"
PY312="${PY312:-$LOCALAPPDATA/Programs/Python/Python312/python.exe}"
