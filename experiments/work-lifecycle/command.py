"""One command per client process, used by all observable-contract tests."""
import argparse
import importlib
import json
import os
from pathlib import Path
import signal
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", choices=("durable_runtime", "paperclip", "goalflow_minimal"))
    parser.add_argument("root", type=Path)
    parser.add_argument("--kill-after", action="store_true")
    args = parser.parse_args()
    request = json.load(sys.stdin)
    backend = importlib.import_module(f"backends.{args.backend}.backend").Backend(args.root)
    response = backend.command(request)
    if args.kill_after:
        os.kill(os.getpid(), signal.SIGKILL)
    print(json.dumps(response, sort_keys=True))


if __name__ == "__main__":
    main()
