"""Own and restart experiment-only native server and Python service processes."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent


def http(url, body=None):
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=2) as response:
        data = response.read()
        return json.loads(data) if data else None


class Manager:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.server = None
        self.service = None
        self.logs = []

    def _spawn(self, args, log):
        stream = (self.root / log).open("ab")
        self.logs.append(stream)
        return subprocess.Popen(args, cwd=HERE, stdout=stream, stderr=stream, start_new_session=True)

    def _await(self, process, url):
        end = time.monotonic() + 40
        while time.monotonic() < end:
            if process.poll() is not None:
                raise RuntimeError(f"Runtime process exited {process.returncode}; inspect {self.root}")
            try:
                http(url)
                return
            except (OSError, ValueError):
                time.sleep(0.15)
        raise RuntimeError(f"Runtime readiness timeout: {url}; inspect {self.root}")

    def start(self):
        # Refuse to reuse an unrelated service occupying our fixed experiment ports.
        for url in ("http://127.0.0.1:18970/health", "http://127.0.0.1:19080/health"):
            try:
                urllib.request.urlopen(url, timeout=0.3)
            except OSError:
                pass
            else:
                raise RuntimeError("Experiment port already occupied: " + url)
        python = HERE / ".runtime/venv/bin/python"
        binary = HERE / ".runtime/restate-server-aarch64-apple-darwin/restate-server"
        if not python.exists() or not binary.exists():
            raise RuntimeError("Run backends/durable_runtime/setup.py first")
        self.service = self._spawn([str(python), str(HERE / "service.py")], "service.log")
        # Hypercorn's /discover is POST; TCP readiness is checked by the registration below.
        self.server = self._spawn([str(binary), "--config-file", str(HERE / "restate.toml"),
                                   "--base-dir", str((self.root / "data").resolve()), "--no-logo"], "server.log")
        self._await(self.server, "http://127.0.0.1:18970/health")
        end = time.monotonic() + 30
        while True:
            try:
                http("http://127.0.0.1:18970/deployments", {"uri": "http://127.0.0.1:19080"})
                break
            except OSError:
                if time.monotonic() > end:
                    raise
                time.sleep(0.2)
        return self

    def restart(self):
        # Hard kill both backing processes, retaining native on-disk journal/state.
        self._stop_process(self.service, signal.SIGKILL)
        self._stop_process(self.server, signal.SIGKILL)
        self.service = self.server = None
        self.start()

    @staticmethod
    def _stop_process(process, sig):
        if process is not None and process.poll() is None:
            os.killpg(process.pid, sig)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)

    def close(self):
        self._stop_process(self.service, signal.SIGTERM)
        self._stop_process(self.server, signal.SIGTERM)
        self.service = self.server = None
        for stream in self.logs:
            stream.close()
        self.logs = []

    def __enter__(self):
        try:
            return self.start()
        except BaseException:
            self.close()
            raise

    def __exit__(self, *exc):
        self.close()
