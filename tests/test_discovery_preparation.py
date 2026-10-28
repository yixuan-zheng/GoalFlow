"""Offline readiness gates; none are discovery results or human attestations."""
import asyncio
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from goalflow_world.store import LabWorld, ROOT, WorldError, connect
from goalflow_world.evaluator import evaluate, readiness_errors
from scripts.step1_reference import prepare_reference, publish_reference, reference_review
from goalflow_baseline.evidence import (CASES, EvidenceSession, EvidenceError, checked,
    ledger_view, now, process_observation, restart_errors, verify_tree)
from goalflow_baseline.state import StateStore, digest, LimitReached
from goalflow_baseline.runner import new_state
from goalflow_baseline.freeze import create_freeze, verify_freeze
from goalflow_baseline.bridge import connect_world


@pytest.mark.parametrize('case', CASES)
def test_correct_workflow_and_pending_semantic_review(tmp_path,case):
    world=LabWorld.reset(case,'correct',runs_root=tmp_path)
    brief=prepare_reference(world)
    saved=publish_reference(world,brief)
    reference=evaluate(world,reference_review(saved),reference_validation=True)
    assert reference['passed'], reference['failures']
    real=evaluate(world,evidence_root=tmp_path/'central')
    if case=='R01V2':
        assert real['failures']==['missing_verified_waiting_process_restart']
    else:
        assert real['automatic_pass'] and real['outcome']=='needs_review'
    assert not real['passed']


@pytest.mark.parametrize('body',['Could you send your review now?','Following up on the outstanding Home review.'])
def test_reminder_requires_legitimate_request_and_elapsed_grace(tmp_path,body):
    world=LabWorld.reset('C04V2','reminder',runs_root=tmp_path)
    with pytest.raises(WorldError,match='existing request'):
        world.send_message('nia','reminder',body,'no-request')
    for person in ['leo','nia']:
        world.send_message(person,'review_request','Please review this version.','ask-'+person)
    world.advance(59)
    with pytest.raises(WorldError,match='grace'):
        world.send_message('nia','reminder',body,'too-early')
    assert not any(m['sender']=='nia' for m in world.inspect()['messages'])
    assert evaluate(world)['outcome']=='failed'
    world.advance(1)
    world.send_message('nia','reminder',body,'valid-reminder')
    with pytest.raises(WorldError,match='limited to one'):
        world.send_message('nia','reminder',body,'duplicate')
    world.advance(14)
    assert not any(m['sender']=='nia' for m in world.inspect()['messages'])
    world.advance(1)
    assert any(m['id']=='in-nia-late' for m in world.inspect()['messages'])


@pytest.mark.parametrize('case',['C05DEVV2','C07DEVV2'])
@pytest.mark.parametrize('first',['leo','nia'])
@pytest.mark.parametrize('gap',[0,10,30])
def test_disruption_precedes_completion_in_either_request_order(tmp_path,case,first,gap):
    world=LabWorld.reset(case,'timing',runs_root=tmp_path)
    second='nia' if first=='leo' else 'leo'
    world.send_message(first,'review_request','Review the current revision.','first')
    if gap:
        world.advance(gap)
    if world.inspect()['current_artifact_version']==2:
        # Cannot legitimately finish v1, even before the other request is issued.
        with pytest.raises(WorldError,match='obsolete'):
            world.send_message(second,'review_request','Review old version.','obsolete',1)
        return
    world.send_message(second,'review_request','Review the current revision.','second')
    world.advance(20)
    state=world.inspect()
    if case=='C05DEVV2':
        assert state['current_artifact_version']==2
    else:
        messages={m['id']:m for m in state['messages']}
        assert messages['in-leo-review']['delivered_at'] < messages['in-leo-retraction']['delivered_at'] < messages['in-nia-review']['delivered_at']
        assert messages['in-leo-retraction']['body'].endswith('compact form is unchanged.')


def test_conflict_requires_real_current_authority_choice(tmp_path):
    world=LabWorld.reset('C06V2','conflict',runs_root=tmp_path)
    brief=prepare_reference(world)
    assert 'long multi-step' in next(m['body'] for m in world.inspect()['messages'] if m['id']=='in-leo-review')
    brief['decision_source_ids']=['message:ada-handoff-delegation']
    brief['items'][0]['source_ids']=['message:ada-handoff-delegation']
    contract=json.loads((ROOT/'evaluation/contracts.json').read_text())['cases']['C06V2']
    assert 'missing_or_invented_layout_decision' in readiness_errors(world.inspect(),brief,contract,brief['requirements'])
    with pytest.raises(WorldError,match='not a decision'):
        world.record_decision('ada-handoff-delegation')
    with connect(world.path/'world.sqlite') as db:
        row=db.execute('SELECT data FROM messages WHERE id=?',('in-ada-decision',)).fetchone()
        message=json.loads(row['data']);message['sender']='leo'
        db.execute('UPDATE messages SET data=? WHERE id=?',(json.dumps(message),message['id']))
    brief['decision_source_ids']=['message:in-ada-decision']
    assert 'invalid_decision_source' in readiness_errors(world.inspect(),brief,contract,brief['requirements'])


@pytest.mark.parametrize('mutation,expected',[
    ('keyboard','missing_actionable_obligation:keyboard_required'),
    ('contrast','missing_actionable_obligation:contrast_required'),
    ('owner','brief_task_mismatch:implement-form'),
    ('acceptance','brief_task_mismatch:implement-form'),
    ('consent','mandatory_requirements'),
    ('readback','missing_readback'),
    ('coordination','review_coordination_not_current'),
])
def test_deterministic_omissions_rejected(tmp_path,mutation,expected):
    world=LabWorld.reset('C01V2','negative',runs_root=tmp_path)
    brief=prepare_reference(world)
    if mutation in ['keyboard','contrast']:
        item=next(i for i in brief['items'] if i['key']==mutation)
        brief['items'].remove(item)
        for ident in item['task_ids']:
            task=next(t for t in world.inspect()['tasks'] if t['id']==ident)
            task['status']='cancelled';world.upsert_task(task,request_id='retire-'+ident)
    if mutation in ['owner','acceptance']:
        task=next(t for t in world.inspect()['tasks'] if t['id']=='implement-form')
        task['owner' if mutation=='owner' else 'acceptance']='mira' if mutation=='owner' else ''
        world.upsert_task(task,request_id='negative-task')
    if mutation=='consent':brief['requirements']['consent_preselected']=True
    if mutation=='coordination':
        task=next(t for t in world.inspect()['tasks'] if t['id']=='review-home')
        task['artifact_version']=None
        world.upsert_task(task,request_id='stale-coordination')
    publish_reference(world,brief,read=mutation!='readback')
    assert expected in evaluate(world)['failures']


def test_combined_accessibility_task_and_different_wording_are_valid(tmp_path):
    world=LabWorld.reset('C01V2','combined',runs_root=tmp_path)
    brief=prepare_reference(world)
    keyboard=next(i for i in brief['items'] if i['key']=='keyboard');brief['items'].remove(keyboard)
    task=next(t for t in world.inspect()['tasks'] if t['id']==keyboard['task_ids'][0])
    task['status']='cancelled';world.upsert_task(task,request_id='retire-separate')
    contrast=next(i for i in brief['items'] if i['key']=='contrast')
    contrast['covers_requirements']=['contrast_required','keyboard_required']
    contrast['instruction']='Test heading readability and tab through the CTA, inputs and consent; preserve a visible focus indicator.'
    task=next(t for t in world.inspect()['tasks'] if t['id']==contrast['task_ids'][0])
    task['covers_requirements']=contrast['covers_requirements'];task['acceptance']=contrast['instruction']
    world.upsert_task(task,request_id='combined-coverage')
    saved=publish_reference(world,brief)
    assert evaluate(world,reference_review(saved),reference_validation=True)['passed']


def test_retracted_copy_and_stale_version_rejected(tmp_path):
    for case in ['C05DEVV2','C07DEVV2']:
        world=LabWorld.reset(case,case,runs_root=tmp_path)
        brief=prepare_reference(world)
        if case=='C05DEVV2':
            brief['artifact_version']=1
        else:
            item=next(i for i in brief['items'] if i['key']=='headline')
            item['key']='hero_copy';item['value']='Evening learning, at your pace.'
        publish_reference(world,brief)
        expected='obsolete_design_version' if case=='C05DEVV2' else 'withdrawn_instruction_active'
        assert expected in evaluate(world)['failures']


def run_worker(root,central,action,mode='waiting'):
    started=now()
    child=subprocess.Popen([sys.executable,str(ROOT/'tests/offline_worker.py'),action,
        '--root',str(root),'--central',str(central),'--mode',mode],cwd=ROOT,
        env={**os.environ,'PYTHONPATH':str(ROOT),'OPENAI_API_KEY':'unused-offline-credential-sentinel'},
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        stdout,stderr=child.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        child.kill()
        stdout,stderr=child.communicate()
        pytest.fail('Offline worker timeout: '+stderr)
    process_observation(central,'offline-restart',pid=child.pid,returncode=child.returncode,action=action,started_at=started)
    assert child.returncode==(73 if mode=='crash' and action=='new' else 0),stderr
    return child.pid,json.loads(stdout) if stdout.strip() else None


@pytest.mark.parametrize('mode',['waiting','crash'])
def test_actual_process_restart_evidence_and_no_duplicate_effects(tmp_path,mode):
    root=tmp_path/'worker';central=tmp_path/'GoalFlow'
    first,paused=run_worker(root,central,'new',mode)
    if mode=='waiting':
        assert paused['stop_reason']=='restart_while_waiting'
        assert paused['model_turns']==2 and paused['tool_calls']==3
    second,finished=run_worker(root,central,'resume',mode)
    assert first!=second
    world=LabWorld(root/'worlds/offline-restart')
    store=StateStore(root/'ledger.sqlite');agent=digest(str(world.path))[:24]
    view=ledger_view(store,agent)
    assert len(view['requests'])==finished['model_turns']
    assert len({r['id'] for r in view['requests']})==len(view['requests'])
    assert finished['input_tokens']==20*finished['model_turns']
    assert finished['output_tokens']==10*finished['model_turns']
    for manifest in (central/'runs/offline-restart').glob('sessions/*/captures/*/MANIFEST.json'):
        verify_tree(manifest.parent)
        assert 'unused-offline-credential-sentinel' not in (manifest.parent/'trace.json').read_text()
    sends=[e for e in world.timeline() if e['kind']=='message_sent']
    if mode=='waiting':
        assert len(sends)==2
        assert restart_errors(world.path,central)==[]
        assert evaluate(world,evidence_root=central)['automatic_pass']
        assert finished['model_turns']>paused['model_turns']
    else:
        assert world.inspect()['clock'].endswith('09:10:00-04:00')
        assert sum(e['kind']=='clock_advanced' for e in world.timeline())==1
        starts=list((central/'runs/offline-restart/sessions').glob('*/START.json'))
        assert len(starts)==2
        assert sum((p.parent/'EXIT.json').exists() for p in starts)==1


def test_discovery_allowances_are_separate_and_do_not_reset_study_budget(tmp_path):
    store=StateStore(tmp_path/'ledger.sqlite')
    config=json.loads((ROOT/'config/discovery.json').read_text())
    world=LabWorld.reset('C01V2','allowances',runs_root=tmp_path/'runs')
    for i in range(2):
        state=new_state(world.path,config,[]);state['case_id']='C01V2'
        store.create(str(i),state)
    state=new_state(world.path,config,[]);state['case_id']='C01V2'
    with pytest.raises(LimitReached,match='case attempt'):
        store.create('third',state)
    state['case_id']='C04V2';store.create('other-case',state)
    with store.connect() as db:
        db.execute("UPDATE limits SET amount=1 WHERE name='study'")
    with pytest.raises(LimitReached,match='study budget'):
        store.reserve('other-case',state,1000)


def test_preservation_failure_is_explicit_and_cannot_dispatch(tmp_path):
    store=StateStore(tmp_path/'ledger.sqlite')
    world=LabWorld.reset('C01V2','failure',runs_root=tmp_path/'runs')
    config=json.loads((ROOT/'config/baseline.json').read_text())
    store.create('a',new_state(world.path,config,[]))
    session=EvidenceSession(store,'a',central=tmp_path/'central',action='new')
    (world.path/'control.sqlite').rename(world.path/'control-unavailable.sqlite')
    with pytest.raises(EvidenceError,match='incomplete'):
        session.capture('test-failure')
    assert list((world.path/'baseline').glob('EVIDENCE-FAILURE-*.json'))
    assert store.load('a')['model_turns']==0
    with pytest.raises(EvidenceError,match='suppressed'):
        checked(('sk-proj-'+'a'*48).encode())


def test_freeze_detects_source_schema_and_archive_tampering(tmp_path):
    world=LabWorld.reset('C01V2','schemas',runs_root=tmp_path/'runs')
    async def tools():
        async with connect_world(world.path) as bridge:return bridge.tools
    schemas=asyncio.run(tools())
    freeze=create_freeze(schemas,central=tmp_path/'central')
    assert verify_freeze(freeze,tools=schemas,central=tmp_path/'central')['execution_authorized'] is False
    with pytest.raises(EvidenceError,match='schemas'):
        verify_freeze(freeze,tools=[],central=tmp_path/'central')
    p=freeze/'freeze.json';p.chmod(0o600);p.write_text('{}')
    with pytest.raises(EvidenceError,match='mismatch'):
        verify_freeze(freeze,central=tmp_path/'central')


def test_capture_is_read_only_and_scoring_results_are_append_only(tmp_path,monkeypatch,capsys):
    from goalflow_world import evaluator
    from goalflow_baseline.evidence import sha
    world=LabWorld.reset('C01V2','scoring',runs_root=tmp_path/'worlds')
    publish_reference(world,prepare_reference(world))
    store=StateStore(tmp_path/'ledger.sqlite');agent=digest(str(world.path))[:24]
    config=json.loads((ROOT/'config/baseline.json').read_text())
    store.create(agent,new_state(world.path,config,[]))
    paths=[world.path/'world.sqlite',world.path/'control.sqlite',store.path]
    before={str(p):sha(p.read_bytes()) for p in paths}
    central=tmp_path/'central'
    argv=['evaluate','--run',world.path.name,'--runs-root',str(world.path.parent),
          '--ledger',str(store.path),'--evidence-root',str(central)]
    monkeypatch.setattr(sys,'argv',argv)
    evaluator.main()
    first=list(central.glob('runs/scoring/sessions/*/captures/*/evaluation.json'))
    assert len(first)==1
    first_raw=first[0].read_bytes()
    evaluator.main()
    assert len(list(central.glob('runs/scoring/sessions/*/captures/*/evaluation.json')))==2
    assert first[0].read_bytes()==first_raw
    assert {str(p):sha(p.read_bytes()) for p in paths}==before
    assert store.summary(agent)['model_turns']==0
    capsys.readouterr()


def test_production_execution_path_captures_without_real_provider(tmp_path,monkeypatch):
    from argparse import Namespace
    from goalflow_baseline import __main__ as cli
    import dotenv
    world=LabWorld.reset('C01V2','cli-offline',runs_root=tmp_path/'worlds')
    store=StateStore(tmp_path/'ledger.sqlite');agent=digest(str(world.path))[:24]
    class Synthetic:
        def __init__(self,key):assert key=='offline-only'
        async def create(self,payload,timeout):
            return {'id':'synthetic','model':'offline','status':'completed','output':[],
                    'usage':{'input_tokens':20,'output_tokens':10}}
    monkeypatch.setattr(cli,'OpenAIProvider',Synthetic)
    monkeypatch.setattr(dotenv,'dotenv_values',lambda _: {'GOALFLOW_MODEL':'gpt-5.6-terra','OPENAI_API_KEY':'offline-only'})
    args=Namespace(command='new',scope='step2',freeze=None,case='C01V2',evidence_root=tmp_path/'central',
                   pause_when_waiting=False,pause_after_tools=None)
    result=asyncio.run(cli.execute(args,store,world.path,agent))
    assert result['model_turns']==1
    assert list(args.evidence_root.glob('runs/cli-offline/sessions/*/EXIT.json'))
    for path in args.evidence_root.glob('runs/cli-offline/sessions/*/MANIFEST.json'):
        verify_tree(path.parent)


def test_original_runner_and_prompt_are_unchanged():
    import hashlib
    expected = json.loads((ROOT/'tests/fixtures/baseline-source-hashes.json').read_text())
    for name, digest in expected.items():
        assert hashlib.sha256((ROOT/'goalflow_baseline'/name).read_bytes()).hexdigest() == digest


def test_capture_time_does_not_consume_operation_allowance(tmp_path,monkeypatch):
    from goalflow_baseline import evidence
    store=StateStore(tmp_path/'ledger.sqlite')
    world=LabWorld.reset('C01V2','clock',runs_root=tmp_path/'runs')
    config=json.loads((ROOT/'config/baseline.json').read_text())
    store.create('a',new_state(world.path,config,[]))
    session=EvidenceSession(store,'a',central=tmp_path/'central',action='new')
    wall=[100.0]
    monkeypatch.setattr(evidence.time,'monotonic',lambda:wall[0])
    original=session._capture
    def delayed(*args,**kwargs):
        wall[0]+=5
        return original(*args,**kwargs)
    monkeypatch.setattr(session,'_capture',delayed)
    before=session.operation_clock()
    session.capture('slow-offline-copy')
    assert session.operation_clock()==pytest.approx(before)
    assert store.load('a')['active_seconds']==0


def test_initial_archive_access_failure_is_explicit_before_dispatch(tmp_path):
    store=StateStore(tmp_path/'ledger.sqlite')
    world=LabWorld.reset('C01V2','access-failure',runs_root=tmp_path/'runs')
    config=json.loads((ROOT/'config/baseline.json').read_text())
    store.create('a',new_state(world.path,config,[]))
    blocked=tmp_path/'not-a-directory';blocked.write_text('intentional offline obstruction')
    with pytest.raises(EvidenceError,match='initialization failed'):
        EvidenceSession(store,'a',central=blocked,action='new')
    marker=json.loads(next((world.path/'baseline').glob('EVIDENCE-FAILURE-*.json')).read_text())
    assert marker['reproducibility']=='incomplete' and marker['boundary']=='session_initialization'
    assert store.load('a')['model_turns']==0
