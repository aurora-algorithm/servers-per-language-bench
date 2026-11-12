#!/usr/bin/env python3
"""The PHP side's server: nginx in front of a pool of php-cgi FastCGI workers, the Windows stand-in for nginx +
php-fpm (php-fpm does not exist on Windows). Started pinned like every other server; nginx and the workers inherit
the mask. Runs Laravel's deploy step (`artisan optimize`: config, events, routes and views cached) with this process's
environment first, and `optimize:clear` when stopped.

usage: python php_stack.py PORT
env:   PHP_WORKERS (default 5, php-fpm's pm.max_children default), PHP_UPSTREAM_KEEPALIVE=1 (nginx keeps its FastCGI
       connections open; off by default as in Laravel's nginx config), DB_PERSISTENT=1 (PDO persistent connections)
"""

import os
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / ".tools"
PHP_DIR = TOOLS / "php"
NGINX_DIR = next(TOOLS.glob("nginx-*"))
APP = ROOT / "php"
RUN = ROOT / ".run" / "nginx"
FIRST_WORKER_PORT = 9101
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

CONF = """worker_processes 1;
error_log logs/error.log warn;
pid logs/nginx.pid;
events {{
    worker_connections 1024;
}}
http {{
    access_log off;
    upstream php {{
        least_conn;
{servers}
{keepalive}
    }}
    server {{
        listen 127.0.0.1:{port};
        root {root};
        index index.php;
        charset utf-8;
        location / {{
            try_files $uri $uri/ /index.php?$query_string;
        }}
        location ~ ^/index\\.php(/|$) {{
            fastcgi_pass php;
{keep_conn}
            fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
            include fastcgi_params;
            fastcgi_hide_header X-Powered-By;
        }}
    }}
}}
"""


def nginx_conf(port: int, workers: int, upstream_keepalive: bool) -> Path:
    for sub in ("logs", "temp", "conf"):
        (RUN / sub).mkdir(parents=True, exist_ok=True)
    (RUN / "conf" / "fastcgi_params").write_bytes((NGINX_DIR / "conf" / "fastcgi_params").read_bytes())
    servers = "\n".join(f"        server 127.0.0.1:{FIRST_WORKER_PORT + i};" for i in range(workers))
    conf = CONF.format(
        servers=servers,
        keepalive=f"        keepalive {workers};" if upstream_keepalive else "",
        keep_conn="            fastcgi_keep_conn on;" if upstream_keepalive else "",
        port=port,
        root=(APP / "public").as_posix(),
    )
    path = RUN / "conf" / "nginx.conf"
    path.write_text(conf)
    return path


def artisan(*args: str) -> None:
    subprocess.check_call([str(PHP_DIR / "php.exe"), "artisan", *args, "--quiet"], cwd=APP, creationflags=NO_WINDOW)


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    port = int(sys.argv[1])
    workers = int(os.environ.get("PHP_WORKERS", "5"))
    conf = nginx_conf(port, workers, os.environ.get("PHP_UPSTREAM_KEEPALIVE") == "1")
    artisan("optimize")
    env = dict(os.environ, PHP_FCGI_MAX_REQUESTS="0")  # php-cgi exits after 500 requests otherwise; fpm's default is 0
    procs = [
        subprocess.Popen(
            [str(PHP_DIR / "php-cgi.exe"), "-b", f"127.0.0.1:{FIRST_WORKER_PORT + i}"],
            cwd=APP,
            env=env,
            creationflags=NO_WINDOW,
        )
        for i in range(workers)
    ]
    procs.append(
        subprocess.Popen(
            [str(NGINX_DIR / "nginx.exe"), "-p", str(RUN), "-c", str(conf)], cwd=RUN, creationflags=NO_WINDOW
        )
    )
    stop = False

    def on_signal(*_: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    try:
        while not stop:
            for p in procs:
                if p.poll() is not None:
                    print(f"php_stack: {p.args[0]} exited with {p.returncode}", file=sys.stderr, flush=True)
                    return 1
            try:
                procs[0].wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
    finally:
        for p in procs:
            p.kill()
        artisan("optimize:clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
