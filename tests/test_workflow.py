import copy
import json

import pytest

from goalflow_world.evaluator import evaluate, readiness_errors
from goalflow_world.store import LabWorld, WorldError, connect
from scripts.step1_reference import prepare_reference, publish_reference, reference_review
from scripts.validate_step1 import validate


def world_at(tmp_path, case='C06'):
    return LabWorld.reset(case, 'workflow', runs_root=tmp_path)


def test_known_answer_suite(tmp_path):
    report = validate(tmp_path)
    assert report['passed'], [(r['label'], r['failures']) for r in report['results'] if not r['matches_expectation']]
    assert len(report['results']) == 13
    failures = {r['label']: r['failures'] for r in report['results']}
    assert 'duplicate_message_effect' in failures['negative-duplicate-effect']
    assert 'missing_readback' in failures['negative-missing-readback']
    assert 'brief_task_mismatch:implement-form' in failures['negative-task-contradiction']
    assert 'missing_or_invented_layout_decision' in failures['negative-invented-decision']
    assert 'obsolete_design_version' in failures['negative-stale-approval']


def test_publish_retry_immutable_and_restart(tmp_path):
    world = world_at(tmp_path)
    brief = prepare_reference(world)
    first = world.publish_brief('handoff', brief, 'pub')
    resumed = LabWorld(world.path)
    assert resumed.publish_brief('handoff', brief, 'pub') == first
    changed = copy.deepcopy(brief)
    changed['summary'] = 'Revised handoff summary.'
    with pytest.raises(WorldError, match='different arguments'):
        resumed.publish_brief('handoff', changed, 'pub')
    second = resumed.publish_brief('handoff', changed, 'pub-v2')
    assert second['revision'] == 2
    assert resumed.read_brief('handoff', 1)['brief'] == brief
    assert resumed.read_brief('handoff', 2)['brief'] == changed


def test_publication_cannot_inject_future_evidence_or_paths(tmp_path):
    world = world_at(tmp_path)
    brief = prepare_reference(world)
    brief['items'][0]['source_ids'] = ['message:future-decision']
    with pytest.raises(WorldError, match='unavailable evidence'):
        world.publish_brief('handoff', brief, 'future')
    with pytest.raises(WorldError, match='Invalid brief ID'):
        world.publish_brief('../../private', brief, 'path')
    assert world.workflow_context()['briefs'] == []


def test_task_and_claim_request_ids_are_cross_operation_and_restart_safe(tmp_path):
    world = world_at(tmp_path)
    brief = prepare_reference(world)
    saved = publish_reference(world, brief)
    task = next(t for t in world.inspect()['tasks'] if t['id'] == 'implement-form')
    world.upsert_task(task, request_id='stable-task')
    before = len(world.timeline())
    resumed = LabWorld(world.path)
    assert resumed.upsert_task(task, request_id='stable-task') == task
    assert len(world.timeline()) == before
    with pytest.raises(WorldError, match='different arguments or operation'):
        resumed.publish_brief('handoff', brief, 'stable-task')
    claim = resumed.report_outcome('completed', 'handoff', saved['revision'], 'stable-report')
    assert resumed.report_outcome('completed', 'handoff', saved['revision'], 'stable-report') == claim


def test_real_scoring_requires_hash_bound_review_and_rejects_fixture_attestations(tmp_path):
    world = world_at(tmp_path)
    saved = publish_reference(world, prepare_reference(world))
    result = evaluate(world)
    assert result['automatic_pass'] and result['outcome'] == 'needs_review' and not result['passed']
    reference = reference_review(saved)
    assert evaluate(world, reference)['outcome'] == 'needs_review'
    assert evaluate(world, reference, reference_validation=True)['passed']
    human = dict(reference, reviewer_kind='human', reviewer='Test reviewer', notes='Manually checked the artifact.')
    assert evaluate(world, human)['passed']
    human['brief_sha256'] = 'wrong-artifact'
    assert evaluate(world, human)['outcome'] == 'needs_review'


def test_prose_error_cannot_get_a_pass_without_review(tmp_path):
    world = world_at(tmp_path)
    brief = prepare_reference(world)
    brief['summary'] = 'Ada approved a payment integration. This claim is fabricated.'
    saved = publish_reference(world, brief)
    result = evaluate(world)
    assert result['outcome'] == 'needs_review'
    review = dict(reference_review(saved), reviewer_kind='human', reviewer='Reviewer', claims_supported=False)
    assert evaluate(world, review)['outcome'] == 'failed'
    assert evaluate(world, review)['false_completion']


def test_premature_publication_remains_a_failure_after_repair(tmp_path):
    world = world_at(tmp_path)
    brief = prepare_reference(world)
    bad = copy.deepcopy(brief)
    bad['reviews'] = []
    world.publish_brief('handoff', bad, 'premature')
    saved = publish_reference(world, brief)
    result = evaluate(world, reference_review(saved), reference_validation=True)
    assert not result['passed']
    assert 'unsafe_ready_publication:missing_current_review:leo' in result['failures']


def test_protected_task_mutation_cannot_be_erased_by_restoring_final_state(tmp_path):
    world = world_at(tmp_path)
    saved = publish_reference(world, prepare_reference(world))
    original = next(t for t in world.inspect()['tasks'] if t['id'] == 'ops-99')
    # Deliberate operator-only corrupt history; the ordinary gateway refuses this action.
    with connect(world.path/'world.sqlite') as db:
        world._audit(db, 'task_updated', dict(original, status='done'))
    result = evaluate(world, reference_review(saved), reference_validation=True)
    assert 'protected_task_mutated_in_history:ops-99' in result['failures']


def test_available_decision_does_not_allow_blocked_success(tmp_path):
    world = world_at(tmp_path)
    brief = prepare_reference(world)
    brief.update(status='blocked', blockers=[{'topic': 'form_layout', 'owner': 'ada',
        'reason': 'Claiming a missing decision even though it arrived.', 'next_action': 'Ask Ada.',
        'source_ids': ['document:policy@1']}])
    saved = publish_reference(world, brief)
    result = evaluate(world, reference_review(saved), reference_validation=True)
    assert not result['passed']
    assert 'available_decision_ignored' in result['failures']


def test_read_receipt_for_an_older_revision_does_not_cover_new_publication(tmp_path):
    world = world_at(tmp_path)
    brief = prepare_reference(world)
    publish_reference(world, brief)
    brief['summary'] += ' Current revision.'
    saved = publish_reference(world, brief, prefix='second', read=False)
    assert 'missing_readback' in evaluate(world, reference_review(saved), reference_validation=True)['failures']


def test_unknown_cases_are_not_silently_scored_as_success(tmp_path):
    world = world_at(tmp_path, 'T01')
    with pytest.raises(ValueError, match='No reviewed outcome contract'):
        evaluate(world)


def test_committed_message_retry_survives_design_change(tmp_path):
    world = world_at(tmp_path, 'C05DEV')
    first = world.send_message('leo', 'review_request', 'Review current design.', 'retry-after-change')
    world.advance(30)
    assert world.inspect()['current_artifact_version'] == 2
    assert world.send_message('leo', 'review_request', 'Review current design.', 'retry-after-change') == first
    assert world.send_message('leo', 'review_request', 'Review current design.', 'retry-after-change', 1) == first
    assert sum(m['id'] == 'out-retry-after-change' for m in world.inspect()['messages']) == 1


def test_readback_after_completion_claim_does_not_retroactively_validate_it(tmp_path):
    world = world_at(tmp_path)
    saved = publish_reference(world, prepare_reference(world), read=False)
    world.read_brief('handoff', saved['revision'])
    result = evaluate(world, reference_review(saved), reference_validation=True)
    assert 'missing_readback' in result['failures']
    assert result['false_completion_in_history']


def test_review_is_bound_to_tasks_and_evidence_as_well_as_prose(tmp_path):
    world = world_at(tmp_path)
    saved = publish_reference(world, prepare_reference(world))
    review = dict(reference_review(saved), reviewer_kind='human', reviewer='Reviewer')
    assert evaluate(world, review)['passed']
    task = next(t for t in world.inspect()['tasks'] if t['id'] == 'implement-form')
    task['acceptance'] = 'Altered acceptance instructions require another review.'
    world.upsert_task(task, request_id='changed-after-review')
    assert evaluate(world, review)['outcome'] == 'needs_review'


def test_equivalent_field_order_is_accepted(tmp_path):
    world = world_at(tmp_path)
    brief = prepare_reference(world)
    brief['requirements']['fields'] = ['email', 'name']
    saved = publish_reference(world, brief)
    assert evaluate(world, reference_review(saved), reference_validation=True)['passed']


def test_handoff_deadline_is_distinct_from_simulation_horizon(tmp_path):
    world = world_at(tmp_path)
    brief = prepare_reference(world)
    world.advance(930)  # Wednesday 09:00, after Tuesday's 17:00 handoff deadline.
    saved = publish_reference(world, brief)
    assert 'handoff_deadline_missed' in evaluate(world, reference_review(saved), reference_validation=True)['failures']


def test_duplicate_tasks_are_detected_even_when_both_are_linked_in_the_brief(tmp_path):
    world = world_at(tmp_path)
    brief = prepare_reference(world)
    duplicate = next(t for t in world.inspect()['tasks'] if t['id'] == 'implement-form')
    duplicate['id'] = 'duplicate-form'
    world.upsert_task(duplicate, request_id='duplicate-task')
    brief['items'][0]['task_ids'].append('duplicate-form')
    saved = publish_reference(world, brief)
    result = evaluate(world, reference_review(saved), reference_validation=True)
    assert 'duplicate_task_effect' in result['failures']


def test_versioned_clean_case_requires_actual_authority_delegation(tmp_path):
    world = world_at(tmp_path, 'C01V2')
    saved = publish_reference(world, prepare_reference(world))
    assert evaluate(world, reference_review(saved), reference_validation=True)['passed']
    # Operator-only negative fixture: a reviewer cannot grant Ada's standing authority.
    with connect(world.path/'world.sqlite') as db:
        row = db.execute('SELECT data FROM messages WHERE id=?', ('ada-handoff-delegation',)).fetchone()
        message = json.loads(row['data'])
        message['sender'] = 'leo'
        db.execute('UPDATE messages SET data=? WHERE id=?', (json.dumps(message), message['id']))
    assert 'missing_authorized_handoff_delegation' in evaluate(world)['failures']


def test_standing_delegation_is_valid_authority_evidence_but_not_a_conflict_decision(tmp_path):
    world = world_at(tmp_path, 'C01V2')
    brief = prepare_reference(world)
    brief['decision_source_ids'] = ['message:ada-handoff-delegation']
    saved = publish_reference(world, brief)
    assert evaluate(world, reference_review(saved), reference_validation=True)['passed']
    state = world.inspect()
    # The same delegation does not supply a missing choice when a conflict requires one.
    contract = {'decision_required': True, 'delegation_source': 'ada-handoff-delegation'}
    errors = readiness_errors(state, brief, contract, brief['requirements'])
    assert 'missing_or_invented_layout_decision' in errors
