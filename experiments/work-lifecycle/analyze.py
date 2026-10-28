"""Validate a completed run and emit auditable accounting and walkthroughs."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from measure import measure
from run import source_hashes
from scenarios import SCENARIOS

HERE = Path(__file__).resolve().parent
BACKENDS = ("durable_runtime", "paperclip", "goalflow_minimal")
DOMAINS = ("coding", "research")
SPEC_SHA256 = "f6ce9d223a0823647bee4f1a2ce9659331540f9eb9739c70e4cebb86b60822ce"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def walkthrough(run, domain, scenario):
    folder = run / "goalflow_minimal" / domain / scenario
    rows = []
    for line in (folder / "trace.jsonl").read_text().splitlines():
        event = json.loads(line)
        if "request" not in event:
            continue
        request = event["request"]
        if not event.get("stdout"):
            continue
        response = json.loads(event["stdout"])
        state = response["state"]
        if request["op"] in ("inspect", "ack"):
            continue
        label = request["op"] + (":" + request["kind"] if "kind" in request else "")
        detail = request.get("reason", request.get("event_id", request.get("attempt_id", "")))
        rows.append(f"| {label} | {response['code']} | {state['revision']} | {state['status']} | {detail} |")
    relative = str(folder.relative_to(HERE))
    return "\n".join([
        f"## {domain}: {scenario}", "", "| Operation | Result | Revision | Work state | Detail |",
        "| --- | --- | --- | --- | --- |", *rows, "",
        f"Full command/response/assertion evidence: [{relative}/trace.jsonl]({relative}/trace.jsonl).", "",
        "Artifacts:", "", *[f"- [{p.name}]({p.relative_to(HERE)})" for p in sorted((folder / "artifacts").iterdir())], "",
    ])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    run = args.run.resolve()
    entries = json.loads((run / "results.json").read_text())
    metadata = json.loads((run / "metadata.json").read_text())
    required = [e for e in entries if not e.get("supplemental")]
    expected = {(b, d, s) for b in BACKENDS for d in DOMAINS for s in SCENARIOS}
    observed = {(e["backend"], e["domain"], e["scenario"]) for e in required}
    if observed != expected or len(required) != 72:
        raise SystemExit("Required 72-cell matrix is incomplete or duplicated")
    if metadata["spec_sha256"] != SPEC_SHA256 or digest(HERE / "SPEC.md") != SPEC_SHA256:
        raise SystemExit("Frozen specification changed")
    for backend in BACKENDS:
        if metadata["source_hashes"][backend] != source_hashes(backend):
            raise SystemExit("Backend source changed since selected run: " + backend)
    provenance = json.loads((HERE / "backends/paperclip/provenance.json").read_text())
    for source in provenance:
        data = (HERE / "backends/paperclip" / source["local_path"]).read_bytes()
        git_blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if git_blob != source["git_blob_sha"]:
            raise SystemExit("Vendored source is not the pinned Git blob: " + source["local_path"])
    transfers = json.loads((run / "transfer.json").read_text())
    if len(transfers) != 3 or not all(x["unchanged"] for x in transfers):
        raise SystemExit("Coding/research transfer changed a backend")
    metrics = measure()
    (HERE / "code-accounting.json").write_text(json.dumps(metrics, indent=2) + "\n")
    summary = {
        "selected_run": str(run.relative_to(HERE)), "spec_sha256": SPEC_SHA256,
        "required": {b: {"passed": sum(e["passed"] for e in required if e["backend"] == b), "total": 24} for b in BACKENDS},
        "supplemental": {b: {"passed": sum(e["passed"] for e in entries if e.get("supplemental") and e["backend"] == b),
                              "total": sum(1 for e in entries if e.get("supplemental") and e["backend"] == b)} for b in BACKENDS},
        "assertions": sum(e["assertions"] for e in entries),
        "all_cases_pass": all(e["passed"] for e in entries), "all_backends_unchanged_on_transfer": True,
        "vendor_git_blobs_verified": True, "code_metric": metrics["decision_metric"],
        "decision": "stop_framework_expansion; preserve_prototype",
        "limits": ["scripted local workers, not LLM reliability", "no human productivity measurement",
                   "Paperclip extraction, not full product", "no independent application/adoption validation"],
    }
    (HERE / "decision.json").write_text(json.dumps(summary, indent=2) + "\n")
    with (HERE / "results.csv").open("w", newline="") as stream:
        fields = ("backend", "domain", "scenario", "supplemental", "passed", "assertions", "elapsed_seconds", "evidence")
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(entries)
    (HERE / "walkthrough.md").write_text("# Artifact-backed workflow walkthroughs\n\n"
        "These are generated from the final GoalFlow run's actual command traces, not hypothetical examples. "
        "The same scenarios also run against Restate and the Paperclip extraction.\n\n" +
        walkthrough(run, "coding", "revision_after_artifact") + "\n" +
        walkthrough(run, "research", "normal_continuation"))
    manifest = {}
    for path in sorted(HERE.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(HERE)
        if any(p.startswith(".") or p == "__pycache__" for p in relative.parts):
            continue
        if relative.parts[0] == "development" or "data" in relative.parts or relative.name == "SHA256SUMS.txt":
            continue
        manifest[str(relative)] = digest(path)
    (HERE / "SHA256SUMS.txt").write_text("".join(f"{sha}  {path}\n" for path, sha in manifest.items()))
    print(json.dumps(summary, indent=2))
    return 0 if summary["all_cases_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
