"""Run the frozen, deterministic comparison and retain raw evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

from scenarios import Case, SCENARIOS

HERE = Path(__file__).resolve().parent


def source_hashes(backend):
    result = {}
    for path in sorted((HERE / "backends" / backend).rglob("*")):
        if path.is_file() and not any(p.startswith(".") or p == "__pycache__" for p in path.relative_to(HERE).parts):
            if path.suffix in (".py", ".mjs", ".ts", ".toml", ".lock"):
                result[str(path.relative_to(HERE))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backends", nargs="+", choices=("durable_runtime", "paperclip", "goalflow_minimal"),
                        default=["durable_runtime", "paperclip", "goalflow_minimal"])
    parser.add_argument("--domains", nargs="+", choices=("coding", "research"), default=["coding", "research"])
    parser.add_argument("--scenarios", nargs="+", choices=tuple(SCENARIOS), default=list(SCENARIOS))
    parser.add_argument("--label", default="comparison")
    parser.add_argument("--supplemental", action="store_true", help="also run concurrency and storage-boundary probes")
    args = parser.parse_args()
    if not args.label.replace("-", "").replace("_", "").isalnum():
        parser.error("label must be alphanumeric with hyphens/underscores")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = HERE / "results" / (stamp + "-" + args.label)
    root.mkdir(parents=True, exist_ok=False)
    metadata = {"started_at": datetime.now(timezone.utc).isoformat(), "python": sys.version, "platform": platform.platform(),
                "spec_sha256": hashlib.sha256((HERE / "SPEC.md").read_bytes()).hexdigest(),
                "arguments": vars(args), "source_hashes": {b: source_hashes(b) for b in args.backends}}
    (root / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    results, transfers = [], []
    manager = None
    try:
        if "durable_runtime" in args.backends:
            from backends.durable_runtime.manager import Manager
            manager = Manager(root / "runtime")
            manager.start()
        for backend in args.backends:
            coding_hash = None
            for domain in args.domains:
                for name in args.scenarios:
                    started = time.monotonic()
                    case = Case(backend, domain, name, root / backend / domain / name,
                                manager if backend == "durable_runtime" else None)
                    entry = {"backend": backend, "domain": domain, "scenario": name}
                    try:
                        SCENARIOS[name](case)
                        entry.update(passed=True, final_status=case.state["status"], assertions=case.assertions)
                    except Exception as error:
                        entry.update(passed=False, error=f"{type(error).__name__}: {error}",
                                     traceback=traceback.format_exc(), assertions=case.assertions)
                        case.record(failure=entry)
                    finally:
                        case.trace.close()
                    entry["elapsed_seconds"] = round(time.monotonic() - started, 3)
                    entry["evidence"] = str(case.root.relative_to(root))
                    results.append(entry)
                    (root / "results.json").write_text(json.dumps(results, indent=2) + "\n")
                    print(f"{'PASS' if entry['passed'] else 'FAIL'} {backend}/{domain}/{name}" +
                          (" — " + entry["error"] if not entry["passed"] else ""), flush=True)
                if args.supplemental:
                    from supplemental import SUPPLEMENTAL, SQLITE_ONLY
                    extras = {**SUPPLEMENTAL, **(SQLITE_ONLY if backend != "durable_runtime" else {})}
                    for name, scenario in extras.items():
                        started = time.monotonic()
                        case = Case(backend, domain, name, root / backend / domain / name,
                                    manager if backend == "durable_runtime" else None)
                        entry = {"backend": backend, "domain": domain, "scenario": name, "supplemental": True}
                        try:
                            scenario(case)
                            entry.update(passed=True, final_status=case.state["status"], assertions=case.assertions)
                        except Exception as error:
                            entry.update(passed=False, error=f"{type(error).__name__}: {error}",
                                         traceback=traceback.format_exc(), assertions=case.assertions)
                            case.record(failure=entry)
                        finally:
                            case.trace.close()
                        entry.update(elapsed_seconds=round(time.monotonic() - started, 3), evidence=str(case.root.relative_to(root)))
                        results.append(entry)
                        (root / "results.json").write_text(json.dumps(results, indent=2) + "\n")
                        print(f"{'PASS' if entry['passed'] else 'FAIL'} {backend}/{domain}/{name}" +
                              (" — " + entry["error"] if not entry["passed"] else ""), flush=True)
                if domain == "coding":
                    coding_hash = source_hashes(backend)
                    (root / f"{backend}-after-coding.json").write_text(json.dumps(coding_hash, indent=2) + "\n")
                elif domain == "research" and coding_hash is not None:
                    transfers.append({"backend": backend, "unchanged": coding_hash == source_hashes(backend),
                                      "coding_hashes": coding_hash, "after_research_hashes": source_hashes(backend)})
        (root / "transfer.json").write_text(json.dumps(transfers, indent=2) + "\n")
    finally:
        if manager:
            manager.close()
    passed = sum(e["passed"] for e in results)
    summary = {"passed": passed, "total": len(results), "failed": len(results) - passed,
               "assertions": sum(e["assertions"] for e in results),
               "finished_at": datetime.now(timezone.utc).isoformat(), "results_directory": str(root)}
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
