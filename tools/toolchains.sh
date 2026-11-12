#!/bin/bash
# Portable toolchains for the four stacks the i7 has no system install of, all unpacked into .tools/ inside the
# workspace and deleted with it: Maven (Spring Boot build), PHP + Composer + nginx (Laravel), Ruby + its MSYS2 devkit
# (Rails; puma, nio4r and bootsnap compile native extensions). JDK 25 and the .NET 10 SDK are already installed.
# usage (Git Bash on the i7, from the workspace):  tools/toolchains.sh [maven|php|nginx|ruby ...]
set -euo pipefail
cd "$(dirname "$0")/.."
T="$PWD/.tools"
mkdir -p "$T/dl"

MAVEN_VERSION=3.9.11
MAVEN_SHA512=03e2d65d4483a3396980629f260e25cac0d8b6f7f2791e4dc20bc83f9514db8d0f05b0479e699a5f34679250c49c8e52e961262ded468a20de0be254d8207076
PHP_ZIP=php-8.5.12-1-nts-Win32-vs17-x64.zip
PHP_SHA256=2a36a2edcb7a5b9252f638fd5e4cf84d7f6e066092654220dc0b63e5cf4e9723
COMPOSER_VERSION=2.11.2
NGINX_VERSION=1.30.6
RUBY_TAG=RubyInstaller-4.0.9-1
RUBY_7Z=rubyinstaller-4.0.9-1-x64.7z
MSYS2_SFX=msys2-base-x86_64-20260927.sfx.exe

fetch() {  # url file
  [ -s "$T/dl/$2" ] || curl -fsSL --retry 3 -o "$T/dl/$2" "$1"
  echo "$(sha256sum "$T/dl/$2" | cut -c1-64)  $2" >> "$T/dl/SHA256SUMS"
}

maven() {
  [ -x "$T/apache-maven-$MAVEN_VERSION/bin/mvn" ] && return
  fetch "https://archive.apache.org/dist/maven/maven-3/$MAVEN_VERSION/binaries/apache-maven-$MAVEN_VERSION-bin.zip" maven.zip
  echo "$MAVEN_SHA512  $T/dl/maven.zip" | sha512sum -c -
  unzip -q "$T/dl/maven.zip" -d "$T"
}

php() {
  if [ ! -x "$T/php/php.exe" ]; then
    fetch "https://windows.php.net/downloads/releases/$PHP_ZIP" php.zip
    echo "$PHP_SHA256  $T/dl/php.zip" | sha256sum -c -
    unzip -q "$T/dl/php.zip" -d "$T/php"
  fi
  # php.ini-production as shipped, plus the extensions Laravel and Composer need (all in the zip's ext/ folder).
  sed -e 's/^;extension_dir = "ext"/extension_dir = "ext"/' \
      -e 's/^;\(extension=\(curl\|fileinfo\|mbstring\|openssl\|pdo_pgsql\|pgsql\|zip\|sodium\)\)$/\1/' \
      "$T/php/php.ini-production" > "$T/php/php.ini"
  fetch "https://getcomposer.org/download/$COMPOSER_VERSION/composer.phar" composer.phar
  cp "$T/dl/composer.phar" "$T/php/composer.phar"
}

nginx() {
  [ -x "$T/nginx-$NGINX_VERSION/nginx.exe" ] && return
  fetch "https://nginx.org/download/nginx-$NGINX_VERSION.zip" nginx.zip
  unzip -q "$T/dl/nginx.zip" -d "$T"
}

ruby() {
  if [ ! -x "$T/ruby/bin/ruby.exe" ]; then
    fetch "https://www.7-zip.org/a/7zr.exe" 7zr.exe
    fetch "https://github.com/oneclick/rubyinstaller2/releases/download/$RUBY_TAG/$RUBY_7Z" ruby.7z
    "$T/dl/7zr.exe" x -y -o"$T" "$T/dl/ruby.7z" > /dev/null
    mv "$T/${RUBY_7Z%.7z}" "$T/ruby"
  fi
  if [ ! -d "$T/ruby/msys64" ]; then  # ridk looks for MSYS2 in <ruby>/msys64 first
    fetch "https://repo.msys2.org/distrib/x86_64/$MSYS2_SFX" msys2.sfx.exe
    "$T/dl/msys2.sfx.exe" -y -o"$(cygpath -w "$T/ruby")" > /dev/null
  fi
  "$T/ruby/bin/ridk.cmd" install 3
}

for tool in "${@:-maven php nginx ruby}"; do
  for t in $tool; do "$t"; done
done
