"""Reproducible source accounting, with a complete explicit file manifest."""
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = {
    "durable_runtime": {
        "lifecycle": ["backends/durable_runtime/service.py"],
        "transport": ["backends/durable_runtime/backend.py"],
        "local_operations": ["backends/durable_runtime/manager.py", "backends/durable_runtime/setup.py"],
        "configuration": ["backends/durable_runtime/restate.toml", "backends/durable_runtime/requirements.lock"],
        "vendor": [],
    },
    "paperclip": {
        "lifecycle": ["backends/paperclip/backend.py"],
        "transport": ["backends/paperclip/arbiter-runner.mjs", "backends/paperclip/resolve-ts.mjs"],
        "local_operations": [],
        "configuration": ["backends/paperclip/package.json"],
        "vendor": ["backends/paperclip/vendor/status-arbiter.ts", "backends/paperclip/vendor/native-provider-failure.ts"],
    },
    "goalflow_minimal": {
        "lifecycle": ["backends/goalflow_minimal/core.py"],
        "transport": ["backends/goalflow_minimal/backend.py"],
        "local_operations": [], "configuration": [], "vendor": [],
    },
    "shared": {
        "applications_and_policy": ["applications.py"],
        "harness": ["command.py", "scenarios.py", "supplemental.py", "sqlite_fault.py", "run.py", "measure.py", "analyze.py"],
    },
}


def count(path):
    text = path.read_text()
    docstring_lines = set()
    if path.suffix == ".py":
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                    value = node.body[0].value
                    if isinstance(value.value, str):
                        docstring_lines.update(range(node.body[0].lineno, node.body[0].end_lineno + 1))
    lines = text.splitlines()
    counted = [i for i, line in enumerate(lines, 1) if line.strip() and i not in docstring_lines
               and not line.lstrip().startswith(("#", "//", "/*", "*", "*/"))]
    return {"physical_lines": len(lines), "nonblank_noncomment_lines": len(counted),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def measure():
    result = {"method": "Count nonblank lines excluding comment-only lines and Python docstrings; inline code counts. "
                         "This is source burden, not human productivity. Dependency source, binaries, generated outputs and documentation excluded. "
                         "Vendored runtime imports/type-only source retained separately. Setup and local service management shown both included and excluded.",
              "backends": {}, "shared": {}, "files": {}}
    for backend, categories in MANIFEST.items():
        totals = {}
        for category, paths in categories.items():
            totals[category] = 0
            for relative in paths:
                counts = count(HERE / relative)
                result["files"][relative] = {"backend": backend, "category": category, **counts}
                totals[category] += counts["nonblank_noncomment_lines"]
        if backend != "shared":
            totals["custom_total"] = sum(v for k, v in totals.items() if k != "vendor")
            totals["custom_excluding_local_operations"] = totals["custom_total"] - totals["local_operations"]
            result["backends"][backend] = totals
        else:
            result["shared"] = totals
    best = min(result["backends"][b]["custom_total"] for b in ("durable_runtime", "paperclip"))
    goalflow = result["backends"]["goalflow_minimal"]["custom_total"]
    result["decision_metric"] = {"best_comparator_custom_total": best, "goalflow_custom_total": goalflow,
                                 "reduction_fraction": round(1 - goalflow / best, 6), "required_reduction": 0.30,
                                 "numeric_threshold_met": goalflow <= best * 0.70}
    return result


if __name__ == "__main__":
    print(json.dumps(measure(), indent=2))
