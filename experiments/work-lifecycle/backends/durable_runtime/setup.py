"""Install pinned official Restate dependencies inside this backend directory."""
from pathlib import Path
import hashlib
import platform
import subprocess
import tarfile
import urllib.request
import venv

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime"
VERSION = "1.8.1"
ARCHIVE = "restate-server-aarch64-apple-darwin.tar.xz"
SHA256 = "e2ea3dce01140981fe4d15a09e53718681574d3a290f5566b1025b4a2696a3eb"


def main():
    if (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        raise SystemExit("Pinned binary targets Apple Silicon macOS. Add an official, verified release artifact for other platforms.")
    downloads = RUNTIME / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / "restate-server.tar.xz"
    if not archive.exists():
        urllib.request.urlretrieve(f"https://github.com/restatedev/restate/releases/download/v{VERSION}/{ARCHIVE}", archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise SystemExit("Restate archive checksum mismatch")
    with tarfile.open(archive) as bundle:
        bundle.extractall(RUNTIME, filter="data")
    environment = RUNTIME / "venv"
    if not environment.exists():
        venv.create(environment, with_pip=True)
    subprocess.run([str(environment / "bin/pip"), "install", "-r", str(ROOT / "requirements.lock")], check=True)
    subprocess.run([str(RUNTIME / "restate-server-aarch64-apple-darwin/restate-server"), "--version"], check=True)


if __name__ == "__main__":
    main()
