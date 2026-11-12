#!/usr/bin/env python3
"""Runs a command pinned to a set of logical CPUs; on Windows the command and its threads inherit the mask from the
first instruction, so runtimes that size themselves at start (.NET's processor count, server-GC heaps) see only them.

usage: python pin.py CPU[,CPU...] COMMAND...
"""
import subprocess
import sys

import psutil


def main() -> int:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    if hasattr(psutil.Process, "cpu_affinity"):  # Windows and Linux; macOS has no affinity (local smoke only)
        psutil.Process().cpu_affinity([int(c) for c in sys.argv[1].split(",")])
    return subprocess.call(sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
