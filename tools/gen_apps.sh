#!/bin/bash
# How php/ and ruby/ were generated (once, on the i7, 2026-11-10): the stock skeletons of Laravel and Rails, then our
# files on top (the controller, the route, a few settings; see README "The eight stacks"). Kept for the record; the
# repo holds the result, and tools/build_ranking.sh installs from its lock files.
# usage: tools/gen_apps.sh php|ruby
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
source tools/ranking_env.sh
export PATH="$RUBY_BIN:$PATH"

case "$1" in
  php)
    "$PHP" "$COMPOSER" create-project laravel/laravel php 13.11.0 --no-scripts --no-interaction --prefer-dist
    (cd php && "$PHP" "$COMPOSER" require firebase/php-jwt:^7.2 --no-interaction)
    ;;
  ruby)
    gem install rails -v 8.1.4.1 --no-document
    ruby "$GEM_HOME/bin/rails" new ruby --name=orders --api --database=postgresql --skip-git --skip-docker --skip-kamal \
      --skip-thruster --skip-solid --skip-ci --skip-test --skip-brakeman --skip-bundler-audit
    (cd ruby && bundle add jwt --version "~> 3.3")
    ;;
esac
