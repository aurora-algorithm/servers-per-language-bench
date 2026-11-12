#!/usr/bin/env python3
"""Runs one command in a Windows pseudo-console and records its screen as an asciinema v2 cast.

usage: python cast.py OUT.cast COLS ROWS -- COMMAND...
The command's own output (hyperfine's live progress and result) is what the video shows.
"""
import json
import sys
import time

import winpty


def main() -> int:
    if len(sys.argv) < 6 or sys.argv[4] != "--":
        sys.exit(__doc__)
    out, cols, rows = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    # A list, not a string: spawn() would split a string itself and keep the quotes.
    proc = winpty.PtyProcess.spawn(sys.argv[5:], dimensions=(rows, cols))
    start = time.monotonic()
    events = []
    while True:
        try:
            data = proc.read(4096)
        except EOFError:
            break
        if data:
            events.append([round(time.monotonic() - start, 6), "o", data])
    proc.wait()
    header = {"version": 2, "width": cols, "height": rows, "timestamp": int(time.time())}
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps(header) + "\n")
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return proc.exitstatus or 0


if __name__ == "__main__":
    sys.exit(main())
