"""Credential-free MCP restart and revised-work demonstration."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from goalflow_world.store import ROOT, LabWorld
from goalflow_world.evaluator import evaluate
from goalflow_baseline.evidence import process_observation, now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = args.output.resolve() if args.output else Path(tempfile.mkdtemp(prefix='goalflow-demo-'))
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        parser.error('Output directory must be empty; existing evidence is never overwritten')
    central = root/'evidence'
    results = []
    for action in ['new', 'resume']:
        started = now()
        with subprocess.Popen([sys.executable, str(ROOT/'tests/offline_worker.py'), action,
             '--root', str(root/'agent'), '--central', str(central)], cwd=ROOT,
             env={**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1'},
             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as child:
            try:
                stdout, stderr = child.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                child.kill(); child.communicate(); raise
            process_observation(central, 'offline-restart', pid=child.pid,
                returncode=child.returncode, action=action, started_at=started)
            if child.returncode:
                raise RuntimeError(stderr)
            results.append({'pid': child.pid, **json.loads(stdout)})
    assert results[0]['stop_reason'] == 'restart_while_waiting'
    assert results[0]['pid'] != results[1]['pid']
    world = LabWorld(root/'agent/worlds/offline-restart')
    score = evaluate(world, evidence_root=central)
    assert score['automatic_pass'] and score['outcome'] == 'needs_review', score
    sys.path.insert(0, str(ROOT/'experiments/work-lifecycle'))
    from scenarios import Case, SCENARIOS
    case = Case('goalflow_minimal', 'coding', 'revision_after_artifact', root/'revision')
    try:
        SCENARIOS['revision_after_artifact'](case)
    finally:
        case.trace.close()
    summary = {'provider': 'scripted; no model requests', 'processes': results,
               'evaluation': score, 'revision_assertions': case.assertions,
               'output': str(root)}
    (root/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
