"""Scripted application workers and independent local completion policies.

Contains no lifecycle transitions. Both applications can use any backend.
"""
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROWS = [
    {"source": "r1", "region": "north", "value": 12},
    {"source": "r2", "region": "south", "value": 20},
    {"source": "r3", "region": "north", "value": 18},
    {"source": "r4", "region": "south", "value": 30},
    {"source": "r5", "region": "north", "value": 24},
    {"source": "r6", "region": "south", "value": 40},
    {"source": "r7", "region": "north", "value": 26},
    {"source": "r8", "region": "south", "value": 50},
]


class Application:
    def __init__(self, domain, root):
        self.domain = domain
        self.root = Path(root) / "artifacts"
        self.root.mkdir(parents=True, exist_ok=True)
        if domain == "research":
            with (self.root / "observations.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=("source", "region", "value"))
                writer.writeheader()
                writer.writerows(ROWS)
        (self.root / "specifications.json").write_text(json.dumps({
            "coding": {
                "1": "shipping_fee(weight, member=False): positive integer weights; base 5 for first unit, plus 2 per additional unit",
                "2": "same tariff; members receive 20% discount; reject nonpositive weights",
            },
            "research": {
                "1": "report all observations: scope, source IDs, count, total, mean",
                "2": "report only north observations, retaining source provenance",
            },
        }, indent=2) + "\n")

    def artifact(self, label, revision=1, valid=True):
        """A finite, separate worker process creates an inspectable artifact."""
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "worker", self.domain,
                                 str(self.root.parent), label, str(revision), "valid" if valid else "invalid"],
                                text=True, capture_output=True, timeout=15, check=True)
        return Path(json.loads(result.stdout)["artifact"])

    def _write_artifact(self, label, revision, valid):
        if self.domain == "coding":
            path = self.root / (label + ".py")
            multiplier = "weight" if not valid else "(weight - 1)"
            discount = " * (0.8 if member else 1)" if revision == 2 else ""
            source = ("def shipping_fee(weight, member=False):\n"
                      "    if not isinstance(weight, int) or weight < 1:\n"
                      "        raise ValueError('positive integer weight required')\n"
                      f"    return (5 + 2 * {multiplier}){discount}\n")
            path.write_text(source)
        else:
            path = self.root / (label + ".json")
            with (self.root / "observations.csv").open(newline="") as stream:
                data = list(csv.DictReader(stream))
            selected = [r for r in data if revision == 1 or r["region"] == "north"]
            total = sum(int(r["value"]) for r in selected)
            report = {"scope": "all" if revision == 1 else "north", "sources": [r["source"] for r in selected],
                      "count": len(selected), "total": total + (0 if valid else 1),
                      "mean": total / len(selected)}
            path.write_text(json.dumps(report, indent=2) + "\n")
            # Preserve the background calculation separately from the final report.
            (self.root / (label + "-background.json")).write_text(json.dumps({
                "sources": [r["source"] for r in selected], "values": [int(r["value"]) for r in selected],
            }, indent=2) + "\n")
        with (self.root / "worker-executions.jsonl").open("a") as stream:
            stream.write(json.dumps({"pid": os.getpid(), "label": label, "revision": revision,
                                     "artifact": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}) + "\n")
        return path

    def verify(self, path, revision, reviewer="maintainer"):
        evidence = {"artifact": str(Path(path).resolve()), "revision": revision, "reviewer": reviewer,
                    "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
        if self.domain == "coding":
            # Execute artifact tests in a separate interpreter; a worker label is not evidence.
            checks = """
import json, runpy, sys
f = runpy.run_path(sys.argv[1])['shipping_fee']
assert f(1) == 5
assert f(3) == 9
try:
    f(0)
except ValueError:
    pass
else:
    raise AssertionError('zero weight accepted')
if int(sys.argv[2]) == 2:
    assert abs(f(1, member=True) - 4) < 1e-9
    assert abs(f(3, member=True) - 7.2) < 1e-9
print(json.dumps({'passed': True}))
"""
            result = subprocess.run([sys.executable, "-I", "-c", checks, str(Path(path).resolve()), str(revision)],
                                    capture_output=True, text=True, timeout=10)
            passed = result.returncode == 0
            evidence.update(verifier="python_subprocess_tests", returncode=result.returncode,
                            stdout=result.stdout, stderr=result.stderr)
        else:
            # Independent verifier uses the fixed ground-truth rows, not worker totals.
            selected = [r for r in ROWS if revision == 1 or r["region"] == "north"]
            total = sum(r["value"] for r in selected)
            expected = {"scope": "all" if revision == 1 else "north", "sources": [r["source"] for r in selected],
                        "count": len(selected), "total": total, "mean": total / len(selected)}
            try:
                actual = json.loads(Path(path).read_text())
                passed = actual == expected
            except (OSError, ValueError):
                actual, passed = None, False
            evidence.update(verifier="fixed_dataset_report_check", expected=expected, observed=actual)
        evidence.update(verification_passed=passed, authorized_reviewer=reviewer == "maintainer")
        return {"authorized": passed and reviewer == "maintainer", "evidence": evidence}


if __name__ == "__main__":
    if len(sys.argv) != 7 or sys.argv[1] != "worker":
        raise SystemExit("usage: applications.py worker DOMAIN ROOT LABEL REVISION valid|invalid")
    application = Application(sys.argv[2], Path(sys.argv[3]))
    artifact = application._write_artifact(sys.argv[4], int(sys.argv[5]), sys.argv[6] == "valid")
    print(json.dumps({"artifact": str(artifact.resolve())}))
