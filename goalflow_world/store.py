import hashlib
import json
import re
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from .models import World, Event, Document, Message, Task
from .workflow import WorkflowOperations

ROOT = Path(__file__).resolve().parents[1]
SAFE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')

class WorldError(ValueError):
    pass

def dump(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)

def add_business_minutes(stamp, minutes, timezone='America/New_York'):
    dt = datetime.fromisoformat(stamp).astimezone(ZoneInfo(timezone))
    # Business clock: Mon–Fri, 09:00–17:00, no holiday calendar in v1.
    def normalize(t):
        while t.weekday() >= 5 or t.hour >= 17:
            t = (t + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        if t.hour < 9:
            t = t.replace(hour=9, minute=0, second=0, microsecond=0)
        return t
    dt = normalize(dt)
    for _ in range(minutes):
        dt = normalize(dt + timedelta(minutes=1))
    return dt.isoformat()

def connect(path):
    c = sqlite3.connect(path, timeout=5)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c

class LabWorld(WorkflowOperations):
    def __init__(self, run_dir):
        self.path = Path(run_dir).resolve()
        if not (self.path/'world.sqlite').exists():
            raise WorldError('Run does not exist; reset a development fixture first')

    @classmethod
    def reset(cls, case_id, run_id, *, replace=False, runs_root=None, fixture_group='development'):
        if not SAFE.fullmatch(case_id) or not SAFE.fullmatch(run_id):
            raise WorldError('Case/run ID must contain letters, numbers, underscores or hyphens')
        if fixture_group not in ['development', 'validation']:
            raise WorldError('Unsupported fixture group')
        fixture = ROOT/'fixtures'/fixture_group/case_id
        if not fixture.is_dir():
            raise WorldError('Unknown development fixture; reserved cases are not provisioned')
        visible_raw = (fixture/'world.json').read_bytes()
        event_raw = (fixture/'events.json').read_bytes()
        visible = World.model_validate_json(visible_raw)
        events = [Event.model_validate(e) for e in json.loads(event_raw)]
        if len({e.id for e in events}) != len(events):
            raise WorldError('Duplicate event IDs')
        path = Path(runs_root or ROOT/'runs')/run_id
        if path.exists():
            if not replace:
                raise WorldError('Run exists; choose a new ID or explicitly pass --replace')
            manifest = path/'manifest.json'
            if not manifest.exists() or json.loads(manifest.read_text()).get('kind') != 'goalflow-local-world':
                raise WorldError('Refusing to replace a directory without a GoalFlow manifest')
            shutil.rmtree(path)
        path.mkdir(parents=True)
        with connect(path/'world.sqlite') as db:
            db.executescript((ROOT/'config/world-schema-v1.sql').read_text())
            db.executescript((ROOT/'config/workflow-schema.sql').read_text())
            data = visible.model_dump()
            for k,v in data.items():
                if k not in ['people','documents','messages','tasks']:
                    db.execute('INSERT INTO metadata VALUES (?,?)',(k,dump(v)))
            for table in ['people','messages','tasks']:
                for item in data[table]:
                    db.execute(f'INSERT INTO {table} VALUES (?,?)',(item['id'],dump(item)))
            for d in data['documents']:
                db.execute('INSERT INTO documents VALUES (?,?,?)',(d['id'],d['version'],dump(d)))
            db.execute('INSERT INTO audit(at,kind,data) VALUES (?,?,?)',(visible.clock,'world_created',dump({'case_id':case_id})))
        # Operator-only control DB. Not included in inspect() or exposed by future tools.
        with connect(path/'control.sqlite') as db:
            db.execute('CREATE TABLE events (id TEXT PRIMARY KEY, spec TEXT NOT NULL, due TEXT, delivered INTEGER NOT NULL DEFAULT 0)')
            for event in events:
                due = add_business_minutes(visible.clock,event.delay_business_minutes,visible.timezone) if event.trigger.get('kind')=='clock' else None
                db.execute('INSERT INTO events(id,spec,due) VALUES (?,?,?)',(event.id,dump(event.model_dump()),due))
        (path/'control.sqlite').chmod(0o600)
        manifest = {'kind':'goalflow-local-world','schema_version':2,'case_id':case_id,'run_id':run_id,'fixture_group':fixture_group,
                    'visible_sha256':hashlib.sha256(visible_raw).hexdigest(),'events_sha256':hashlib.sha256(event_raw).hexdigest(),
                    'mode':'offline-synthetic','created_at':datetime.now(ZoneInfo('UTC')).isoformat()}
        (path/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        return cls(path)

    def _meta(self, db):
        return {r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM metadata')}

    def _audit(self, db, kind, data, at=None):
        db.execute('INSERT INTO audit(at,kind,data) VALUES (?,?,?)',(at or self._meta(db)['clock'],kind,dump(data)))

    def inspect(self):
        with connect(self.path/'world.sqlite') as db:
            out=self._meta(db)
            for table in ['people','documents','messages','tasks','decisions']:
                order='id,version' if table=='documents' else 'id'
                out[table]=[json.loads(r['data']) for r in db.execute(f'SELECT data FROM {table} ORDER BY {order}')]
            return out

    def timeline(self):
        with connect(self.path/'world.sqlite') as db:
            return [dict(seq=r['seq'],at=r['at'],kind=r['kind'],data=json.loads(r['data'])) for r in db.execute('SELECT * FROM audit ORDER BY seq')]

    def send_message(self, recipient, topic, body, request_id, artifact_version=None, subject=None):
        if not SAFE.fullmatch(request_id):
            raise WorldError('Invalid request ID')
        if topic not in ['review_request','clarification','reminder','status_request']:
            raise WorldError('Unsupported message topic')
        if topic=='clarification' and subject not in ['form_layout','scope','review_status']:
            raise WorldError('Clarification requires a supported subject')
        if not body.strip() or len(body)>6000:
            raise WorldError('Message must be nonempty and at most 6000 characters')
        with connect(self.path/'world.sqlite') as db:
            db.execute('BEGIN IMMEDIATE')
            meta=self._meta(db)
            if not db.execute('SELECT 1 FROM people WHERE id=?',(recipient,)).fetchone() or recipient=='coordinator':
                raise WorldError('Recipient is not an allowed test participant')
            old=db.execute('SELECT * FROM effects WHERE request_id=?',(request_id,)).fetchone()
            previous_message=None
            if old:
                previous_message=db.execute('SELECT data FROM messages WHERE id=?',('out-'+request_id,)).fetchone()
            # A retry of an already committed request must remain replayable after a version change.
            version=(artifact_version if artifact_version is not None else
                     json.loads(previous_message['data'])['artifact_version'] if previous_message else meta['current_artifact_version'])
            args={'recipient':recipient,'topic':topic,'body':body,'artifact_version':version,'subject':subject}
            signature=hashlib.sha256(dump(args).encode()).hexdigest()
            if old:
                if old['signature']!=signature:
                    raise WorldError('Request ID reused with different arguments')
                return json.loads(old['result'])
            if version!=meta['current_artifact_version']:
                raise WorldError('Cannot request new work on an obsolete artifact version')
            if topic=='review_request' and recipient not in meta['required_reviewers']:
                raise WorldError('Review requests must target a required reviewer')
            if topic=='reminder':
                prior=[json.loads(r['data']) for r in db.execute('SELECT data FROM messages')]
                relevant=[m for m in prior if m['sender']=='coordinator' and m['recipient']==recipient and m.get('artifact_version')==version]
                requests=[m for m in relevant if m['topic']=='review_request']
                if not requests or any(m['topic']=='reminder' for m in relevant):
                    raise WorldError('Reminder requires an existing request and is limited to one per version')
                earliest=add_business_minutes(requests[0]['delivered_at'],60,meta['timezone'])
                if datetime.fromisoformat(meta['clock'])<datetime.fromisoformat(earliest):
                    raise WorldError('Reminder grace period has not elapsed')
            msg=Message(id='out-'+request_id,sender='coordinator',recipient=recipient,thread=meta['project_id'],topic=topic,
                body=body,authored_at=meta['clock'],delivered_at=meta['clock'],artifact_version=version,subject=subject).model_dump()
            db.execute('INSERT INTO messages VALUES (?,?)',(msg['id'],dump(msg)))
            result={'message_id':msg['id'],'status':'recorded_locally','external_email_sent':False}
            db.execute('INSERT INTO effects VALUES (?,?,?)',(request_id,signature,dump(result)))
            self._audit(db,'message_sent',msg)
        # Event arming can be replayed from outbound records after an interruption.
        self._arm_events()
        return result

    def _arm_events(self):
        state=self.inspect()
        outbound=[m for m in state['messages'] if m['sender']=='coordinator']
        with connect(self.path/'control.sqlite') as db:
            for row in db.execute('SELECT * FROM events WHERE due IS NULL AND delivered=0').fetchall():
                spec=json.loads(row['spec']); trigger=spec['trigger']
                matches=[m for m in outbound if all(m.get(k)==v for k,v in trigger.items() if k!='kind')]
                if trigger.get('kind')=='message_sent' and matches:
                    sent=min(m['delivered_at'] for m in matches)
                    due=add_business_minutes(sent,spec['delay_business_minutes'],state['timezone'])
                    db.execute('UPDATE events SET due=? WHERE id=?',(due,row['id']))
                elif trigger.get('kind') == 'all_messages_sent':
                    # Operator fixture condition, not an agent action sequence: both
                    # legitimate requests must exist, in either order and any wording.
                    groups = [[m for m in outbound if all(m.get(k) == v for k, v in required.items())]
                              for required in trigger['messages']]
                    if groups and all(groups):
                        sent = max(min(m['delivered_at'] for m in group) for group in groups)
                        due = add_business_minutes(sent, spec['delay_business_minutes'], state['timezone'])
                        db.execute('UPDATE events SET due=? WHERE id=?', (due, row['id']))

    def advance(self, minutes, request_id=None):
        if not isinstance(minutes,int) or not 0<=minutes<=960:
            raise WorldError('Advance must be 0–960 business minutes')
        self._arm_events()
        # One SQLite transaction across both files avoids a delivered flag without its world effect.
        with connect(self.path/'world.sqlite') as db:
            db.execute('ATTACH DATABASE ? AS control',(str(self.path/'control.sqlite'),))
            db.execute('BEGIN IMMEDIATE')
            if request_id is not None:
                signature, prior = self._effect(db, 'advance_clock', request_id, {'minutes': minutes})
                if prior is not None:
                    return prior
            meta=self._meta(db)
            target=add_business_minutes(meta['clock'],minutes,meta['timezone'])
            if datetime.fromisoformat(target)>datetime.fromisoformat(meta['deadline']):
                raise WorldError('Advance exceeds fixture horizon')
            rows=db.execute('SELECT * FROM control.events WHERE delivered=0 AND due IS NOT NULL ORDER BY due,id').fetchall()
            count=0
            for row in rows:
                if datetime.fromisoformat(row['due'])>datetime.fromisoformat(target):
                    continue
                spec=json.loads(row['spec'])
                self._deliver(db,spec,row['due'])
                db.execute('UPDATE control.events SET delivered=1 WHERE id=?',(row['id'],))
                count+=1
            db.execute('UPDATE metadata SET value=? WHERE key=?',(dump(target),'clock'))
            self._audit(db,'clock_advanced',{'business_minutes':minutes,'events_delivered':count},target)
            result = {'clock':target,'events_delivered':count}
            if request_id is not None:
                db.execute('INSERT INTO effects VALUES (?,?,?)',(request_id,signature,dump(result)))
        return result

    def _deliver(self,db,event,due):
        payload=event['payload']; kind=event['kind']
        if kind=='message':
            raw=dict(payload,delivered_at=due)
            raw.setdefault('authored_at',due)
            m=Message.model_validate(raw).model_dump()
            if not db.execute('SELECT 1 FROM people WHERE id=?',(m['sender'],)).fetchone():
                raise WorldError('Scripted sender is unknown')
            old=db.execute('SELECT data FROM messages WHERE id=?',(m['id'],)).fetchone()
            if old:
                old_msg=json.loads(old['data'])
                # Duplicate deliveries retain the original authored/delivery timestamps.
                if any(old_msg[k]!=m[k] for k in m if k not in ['delivered_at','authored_at']):
                    raise WorldError('Conflicting message reused an inbound ID')
                self._audit(db,'duplicate_delivery_ignored',{'event_id':event['id'],'message_id':m['id']},due)
                return
            db.execute('INSERT INTO messages VALUES (?,?)',(m['id'],dump(m)))
        elif kind=='version_change':
            d=Document.model_validate(payload['document']).model_dump()
            for row in db.execute('SELECT * FROM documents WHERE id=?',(d['id'],)).fetchall():
                old=json.loads(row['data']);old['current']=False
                db.execute('UPDATE documents SET data=? WHERE id=? AND version=?',(dump(old),old['id'],old['version']))
            db.execute('INSERT INTO documents VALUES (?,?,?)',(d['id'],d['version'],dump(d)))
            db.execute('UPDATE metadata SET value=? WHERE key=?',(dump(d['version']),'current_artifact_version'))
            # Decisions remain recorded, but are not valid for a different version.
        elif kind=='scope_change':
            for key,value in payload.get('metadata',{}).items():
                if key not in ['decision_maker','required_reviewers']:
                    raise WorldError('Unsupported scenario metadata change')
                db.execute('UPDATE metadata SET value=? WHERE key=?',(dump(value),key))
            if payload.get('message'):
                self._deliver(db,dict(id=event['id']+'-notice',kind='message',payload=payload['message']),due)
        self._audit(db,'event_delivered',{'event_id':event['id'],'kind':kind,'payload':payload},due)

    def record_decision(self,message_id):
        with connect(self.path/'world.sqlite') as db:
            meta=self._meta(db)
            row=db.execute('SELECT data FROM messages WHERE id=?',(message_id,)).fetchone()
            if not row:
                raise WorldError('Decision source is not yet visible')
            m=json.loads(row['data']); decision=m.get('decision')
            if not decision or m['sender']!=meta['decision_maker']:
                raise WorldError('Message is not a decision from the current authority')
            if m['artifact_version']!=meta['current_artifact_version']:
                raise WorldError('Decision refers to an obsolete artifact')
            person=json.loads(db.execute('SELECT data FROM people WHERE id=?',(m['sender'],)).fetchone()['data'])
            if decision.get('topic') not in person['can_decide']:
                raise WorldError('Decision is outside this actor’s authority')
            result={'id':'decision-'+message_id,'source_id':message_id,'actor':m['sender'],
                    'artifact_version':m['artifact_version'],'decision':decision}
            inserted = db.execute('INSERT OR IGNORE INTO decisions VALUES (?,?)',(result['id'],dump(result)))
            if inserted.rowcount:
                self._audit(db,'decision_recorded',result)
            return result

    def upsert_task(self,task_data,request_id=None):
        task=Task.model_validate(task_data).model_dump()
        with connect(self.path/'world.sqlite') as db:
            db.execute('BEGIN IMMEDIATE')
            if request_id is not None:
                signature, prior = self._effect(db, 'upsert_task', request_id, task)
                if prior is not None:
                    return prior
            if not db.execute('SELECT 1 FROM people WHERE id=?',(task['owner'],)).fetchone():
                raise WorldError('Unknown task owner')
            old=db.execute('SELECT data FROM tasks WHERE id=?',(task['id'],)).fetchone()
            if (old and json.loads(old['data'])['protected']) or task['protected']:
                raise WorldError('Protected fixture tasks cannot be mutated')
            db.execute('INSERT INTO tasks VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(task['id'],dump(task)))
            self._audit(db,'task_updated',task)
            if request_id is not None:
                db.execute('INSERT INTO effects VALUES (?,?,?)',(request_id,signature,dump(task)))
        return task
