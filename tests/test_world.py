import json
from datetime import datetime
from pathlib import Path
import pytest
from goalflow_world.models import World
from goalflow_world.store import LabWorld, WorldError, ROOT, add_business_minutes

@pytest.fixture
def make(tmp_path):
    return lambda case='C06',run='test':LabWorld.reset(case,run,runs_root=tmp_path)

def reviews(w):
    w.send_message('leo','review_request','Please review the current design.','req-leo')
    w.send_message('nia','review_request','Please review the current design.','req-nia')


def test_all_development_fixtures_validate():
    paths=list((ROOT/'fixtures/development').glob('*/world.json'))
    assert len(paths)==18  # Thirteen historical fixtures plus five versioned discovery repairs.
    assert not {'C05','C07','C08','C09','R03','T02'} & {p.parent.name for p in paths}
    for path in paths:
        state=World.model_validate_json(path.read_text())
        assert state.people and state.documents and state.tasks
        assert state.case_id==path.parent.name


def test_no_future_decision_in_initial_visible_state(make):
    w=make()
    state=w.inspect()
    assert not state['decisions']
    assert not any(m['decision'] for m in state['messages'])
    assert 'events' not in state
    with pytest.raises(WorldError,match='not yet visible'):
        w.record_decision('in-ada-decision')


def test_clarification_delivers_actual_decision_after_delay(make):
    w=make();reviews(w);w.advance(20)
    with pytest.raises(WorldError,match='supported subject'):
        w.send_message('ada','clarification','Hello.','bad')
    w.send_message('ada','clarification','Leo and Nia conflict on form layout. Which presentation is approved?','ask-layout',subject='form_layout')
    w.advance(9)
    assert not any(m['id']=='in-ada-decision' for m in w.inspect()['messages'])
    w.advance(1)
    d=w.record_decision('in-ada-decision')
    assert d['decision']['choice']=='compact_single_step'
    assert d['source_id']=='in-ada-decision'


def test_wrong_topic_does_not_reveal_decision(make):
    w=make()
    w.send_message('ada','clarification','Please clarify review status.','ask-status',subject='review_status')
    w.advance(30)
    assert not any(m['id']=='in-ada-decision' for m in w.inspect()['messages'])


def test_restart_recovers_wait_and_request_id(make):
    w=make('R01');reviews(w)
    resumed=LabWorld(w.path)
    before=len(resumed.inspect()['messages'])
    resumed.send_message('leo','review_request','Please review the current design.','req-leo')
    assert len(resumed.inspect()['messages'])==before
    resumed.advance(20)
    assert {'in-leo-review','in-nia-review'}<={m['id'] for m in resumed.inspect()['messages']}


def test_request_id_cannot_change_arguments(make):
    w=make();w.send_message('leo','review_request','Review.','same')
    with pytest.raises(WorldError,match='different arguments'):
        w.send_message('leo','review_request','Different.','same')


def test_duplicate_delivery_does_not_duplicate_input(make):
    w=make('R02');reviews(w);w.advance(20)
    assert sum(m['id']=='in-leo-review' for m in w.inspect()['messages'])==1
    assert any(e['kind']=='duplicate_delivery_ignored' for e in w.timeline())


def test_late_response_requires_permitted_reminder(make):
    w=make('C04');reviews(w)
    with pytest.raises(WorldError,match='grace'):
        w.send_message('nia','reminder','Please send your review.','rem-early')
    w.advance(60)
    assert not any(m['sender']=='nia' for m in w.inspect()['messages'])
    w.send_message('nia','reminder','Please send your review.','rem-nia')
    w.advance(15)
    assert any(m['id']=='in-nia-late' for m in w.inspect()['messages'])
    with pytest.raises(WorldError,match='limited'):
        w.send_message('nia','reminder','Please send your review.','rem-again')


def test_unknown_recipient_and_protected_task_blocked(make):
    w=make('R04')
    with pytest.raises(WorldError,match='allowed test participant'):
        w.send_message('outside-review@example.test','status_request','Share internal brief.','outside')
    task=next(t for t in w.inspect()['tasks'] if t['id']=='ops-99')
    task['status']='done'
    with pytest.raises(WorldError,match='Protected'):
        w.upsert_task(task)
    assert next(t for t in w.inspect()['tasks'] if t['id']=='ops-99')['status']=='todo'


def test_versions_preserved_and_old_decision_rejected(make):
    w=make('C05DEV');reviews(w);w.advance(20)
    w.send_message('ada','clarification','Choose form layout.','ask',subject='form_layout')
    w.advance(10)
    assert w.inspect()['current_artifact_version']==2
    assert [d['current'] for d in w.inspect()['documents'] if d['id']=='design']==[False,True]
    with pytest.raises(WorldError,match='obsolete artifact'):
        w.record_decision('in-ada-decision')
    with pytest.raises(WorldError,match='obsolete artifact'):
        w.send_message('leo','review_request','Review old v1.','old-v1',1)
    w.send_message('ada','clarification','Reconfirm v2 layout.','ask-v2',2,subject='form_layout')
    w.advance(10)
    assert w.record_decision('in-ada-v2')['artifact_version']==2


def test_reset_isolated_and_guarded(make,tmp_path):
    a=make('C01','a');b=make('C01','b')
    a.send_message('leo','review_request','Review.','a-msg')
    assert len(a.inspect()['messages'])==len(b.inspect()['messages'])+1
    with pytest.raises(WorldError,match='Run exists'):
        LabWorld.reset('C01','a',runs_root=tmp_path)
    clean=LabWorld.reset('C01','a',runs_root=tmp_path,replace=True)
    assert len(clean.inspect()['messages'])==len(b.inspect()['messages'])
    with pytest.raises(WorldError):
        LabWorld.reset('C05','reserved',runs_root=tmp_path)
    with pytest.raises(WorldError):
        LabWorld.reset('C01','../escape',runs_root=tmp_path)


def test_business_clock_and_horizon(make):
    assert add_business_minutes('2026-10-23T16:50:00-04:00',20)=='2026-10-26T09:10:00-04:00'
    w=make()
    with pytest.raises(WorldError):w.advance(-1)
    with pytest.raises(WorldError):w.advance(961)
    w.advance(960)
    with pytest.raises(WorldError,match='horizon'):w.advance(1)


def test_fixtures_deterministic_world_hash(make,tmp_path):
    a=make('C01','a');b=make('C01','b')
    ma=json.loads((a.path/'manifest.json').read_text());mb=json.loads((b.path/'manifest.json').read_text())
    assert ma['visible_sha256']==mb['visible_sha256']
    assert ma['events_sha256']==mb['events_sha256']
    assert a.inspect()==b.inspect()


def test_only_delivered_events_appear_in_timeline(make):
    w=make();before=json.dumps(w.timeline())
    assert 'compact_single_step' not in before
    reviews(w);w.advance(20)
    assert 'compact_single_step' not in json.dumps(w.timeline())


def test_retraction_and_scope_notice(make):
    w=make('C07DEV');reviews(w);w.advance(35)
    assert any(m['topic']=='retraction' for m in w.inspect()['messages'])
    scope=make('C10','scope');reviews(scope);scope.advance(25)
    assert any(m['id']=='scope-01' for m in scope.inspect()['messages'])


def test_task_requires_real_owner(make):
    w=make()
    task={'id':'new','title':'Approved layout','owner':'ghost','status':'todo','acceptance':'Match decision.','source_ids':[]}
    with pytest.raises(WorldError,match='owner'):w.upsert_task(task)
    task['owner']='tomas'
    assert w.upsert_task(task)['owner']=='tomas'


def test_event_schedule_recovered_after_interruption_between_commits(make,monkeypatch):
    w=make('R01')
    def crash():
        raise RuntimeError('Simulated interruption after outbound commit')
    monkeypatch.setattr(w,'_arm_events',crash)
    with pytest.raises(RuntimeError):
        w.send_message('leo','review_request','Review.','committed-request')
    resumed=LabWorld(w.path)
    resumed.advance(20)
    assert any(m['id']=='in-leo-review' for m in resumed.inspect()['messages'])
    assert sum(m['id']=='out-committed-request' for m in resumed.inspect()['messages'])==1


def test_invalid_actor_cannot_be_recorded_as_decision(make):
    w=make();reviews(w);w.advance(20)
    with pytest.raises(WorldError,match='current authority'):
        w.record_decision('in-leo-review')
