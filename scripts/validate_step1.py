"""Offline known-answer proof. Does not run a model, baseline, or external service."""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path

from goalflow_world.evaluator import evaluate
from goalflow_world.store import LabWorld, ROOT
from scripts.step1_reference import prepare_reference, publish_reference, reference_review


def validate(runs_root):
    results = []

    def record(label, world, saved, expected):
        review = reference_review(saved) if saved else None
        result = evaluate(world, review, reference_validation=True)
        result.update(label=label, expected=expected, matches_expectation=result['outcome'] == expected)
        results.append(result)
        if review:
            (world.path/'reference-review.json').write_text(json.dumps(review, indent=2) + '\n')

    for case in ['C01', 'C04', 'C06', 'C05DEV', 'C07DEV', 'R01', 'VBLOCK']:
        world = LabWorld.reset(case, 'correct-' + case, runs_root=runs_root,
                               fixture_group='validation' if case == 'VBLOCK' else 'development')
        brief = prepare_reference(world)
        saved = publish_reference(world, brief)
        record('correct-' + case, world, saved, 'correctly_blocked' if case == 'VBLOCK' else 'completed')

    noop = LabWorld.reset('C06', 'negative-noop', runs_root=runs_root)
    record('negative-noop', noop, None, 'failed')
    for label in ['invented-decision', 'stale-approval', 'duplicate-effect', 'task-contradiction', 'missing-readback']:
        case = 'C05DEV' if label == 'stale-approval' else 'C06'
        world = LabWorld.reset(case, 'negative-' + label, runs_root=runs_root)
        brief = prepare_reference(world)
        if label == 'invented-decision':
            brief['items'][0]['value'] = 'long_multi_step'
            brief['items'][0]['instruction'] = 'Use a long multi-step form; this decision was never made.'
        if label == 'stale-approval':
            brief['artifact_version'] = 1
            brief['decision_source_ids'] = ['message:in-ada-decision']
        if label == 'duplicate-effect':
            world.send_message('leo', 'review_request', 'Please review the current Home design.', 'second-semantic-request')
        saved = publish_reference(world, brief, read=label != 'missing-readback')
        if label == 'task-contradiction':
            task = copy.deepcopy(next(t for t in world.inspect()['tasks'] if t['id'] == 'implement-form'))
            task['change_value'] = 'long_multi_step'
            world.upsert_task(task, request_id='contradict-task')
        record('negative-' + label, world, saved, 'failed')
    report = {'kind': 'step1-known-answer-validation', 'model_requests': 0, 'external_writes': 0,
              'review_note': 'Reference-fixture attestations only; no human-reviewed agent results.',
              'passed': all(r['matches_expectation'] for r in results), 'results': results}
    (runs_root/'validation-report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs-root', type=Path)
    args = parser.parse_args()
    path = args.runs_root or ROOT/'runs'/('step1-validation-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    path.mkdir(parents=True, exist_ok=False)
    report = validate(path)
    print(json.dumps({'passed': report['passed'], 'checks': len(report['results']), 'report': str(path/'validation-report.json'),
                      'model_requests': 0, 'external_writes': 0}, indent=2))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
