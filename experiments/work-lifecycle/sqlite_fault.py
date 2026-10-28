"""Test-only fault injection; no backend contains a test failure switch."""
import importlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys

original_connect = sqlite3.connect


class CrashConnection(sqlite3.Connection):
    def execute(self, sql, parameters=()):
        result = super().execute(sql, parameters)
        if sql.startswith(("INSERT INTO work VALUES", "INSERT INTO issues VALUES")):
            os.kill(os.getpid(), signal.SIGKILL)
        return result


def connect(*args, **kwargs):
    return original_connect(*args, factory=CrashConnection, **kwargs)


if sys.argv[1] not in ("paperclip", "goalflow_minimal"):
    raise SystemExit("SQLite-only fault injection")
sqlite3.connect = connect
backend = importlib.import_module("backends." + sys.argv[1] + ".backend").Backend(Path(sys.argv[2]))
backend.command(json.load(sys.stdin))
raise SystemExit("fault injection did not fire")
