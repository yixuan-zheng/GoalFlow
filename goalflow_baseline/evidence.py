"""Operator-only append-only evidence. No model/provider or agent policy imports.

World/control snapshots hold shared read locks on BOTH databases. The ledger has
its own transaction; it is not claimed atomic with the application databases.
Capture runs synchronously while the host owns the run lock, before it continues.
"""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import tomllib
import uuid

from goalflow_world.store import ROOT

CENTRAL = Path(os.environ.get('GOALFLOW_EVIDENCE_ROOT', str(ROOT/'output/evidence'))).expanduser().resolve()
CASES = ['C01V2', 'C04V2', 'C06V2', 'C05DEVV2', 'C07DEVV2', 'R01V2']
SECRET = re.compile(rb'(?<![A-Za-z0-9_-])sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{30,}|ya29\.[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')


class EvidenceError(ValueError):
    pass


class WaitingBoundary(BaseException):
    """A host checkpoint boundary, not a model instruction or failed tool call."""


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode()


def checked(data):
    if SECRET.search(data):
        raise EvidenceError('Credential-pattern scan failed; value suppressed')
    return data


def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as output:
        output.write(checked(data))


def seal(folder, metadata):
    records = {str(p.relative_to(folder)): sha(p.read_bytes()) for p in sorted(folder.rglob('*')) if p.is_file()}
    write_new(folder/'MANIFEST.json', encode({**metadata, 'files': records}))
    records['MANIFEST.json'] = sha((folder/'MANIFEST.json').read_bytes())
    write_new(folder/'SHA256SUMS.txt', ''.join(f'{v}  {k}\n' for k, v in sorted(records.items())).encode())
    for name, digest in records.items():
        assert sha((folder/name).read_bytes()) == digest
    for p in folder.rglob('*'):
        if p.is_file():
            p.chmod(0o444)
    # Directories stay owner-writable to permit new, uniquely named siblings.
    return sha((folder/'MANIFEST.json').read_bytes())


def verify_tree(folder):
    manifest = json.loads((folder/'MANIFEST.json').read_text())
    for name, expected in manifest['files'].items():
        path = folder/name
        if path.is_symlink() or sha(path.read_bytes()) != expected:
            raise EvidenceError('Archived file integrity mismatch')
    for line in (folder/'SHA256SUMS.txt').read_text().splitlines():
        expected, name = line.split('  ', 1)
        if sha((folder/name).read_bytes()) != expected:
            raise EvidenceError('Archive checksum mismatch')
    return manifest


def source_files():
    files = [ROOT/'pyproject.toml', ROOT/'uv.lock']
    for directory, pattern in [('goalflow_baseline','*.py'), ('goalflow_baseline','*.md'),
                               ('goalflow_world','*.py'), ('tools','world_server.py'),
                               ('config','*.json'), ('config','*.sql'), ('evaluation','contracts.json'),
                               ('scripts','*.py'), ('tests','*.py')]:
        files.extend((ROOT/directory).glob(pattern))
    for case in CASES:
        files.extend((ROOT/'fixtures/development'/case).glob('*.*'))
    return sorted(set(p for p in files if p.is_file()))


def versions():
    installed = {}
    for package in tomllib.loads((ROOT/'uv.lock').read_text())['package']:
        name = package['name']
        try:
            installed[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue  # Project itself and non-current-platform optional dependencies.
    return {'python': sys.version.split()[0], 'packages': installed}


def source_snapshot(central):
    payloads = {str(p.relative_to(ROOT)): checked(p.read_bytes()) for p in source_files()}
    hashes = {name: sha(raw) for name, raw in payloads.items()}
    identity = sha(encode({'files': hashes, 'dependencies': versions()}))
    folder = central/'project/frozen-sources'/identity
    if folder.exists():
        verify_tree(folder)
    else:
        folder.mkdir(parents=True, exist_ok=False)
        for name, raw in payloads.items():
            write_new(folder/name, raw)
        seal(folder, {'kind': 'exact-source-snapshot', 'identity': identity, 'dependencies': versions()})
    return identity


def readonly(path):
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def database_pair(run_path, destination):
    guard = readonly(run_path/'world.sqlite')
    try:
        guard.execute('ATTACH DATABASE ? AS control', ((run_path/'control.sqlite').resolve().as_uri()+'?mode=ro',))
        if any(guard.execute(f'PRAGMA {schema}.journal_mode').fetchone()[0]=='wal' for schema in ['main','control']):
            raise EvidenceError('Cross-database WAL capture is unsupported; stop rather than imply atomicity')
        guard.execute('BEGIN')
        guard.execute('SELECT count(*) FROM sqlite_master').fetchone()
        guard.execute('SELECT count(*) FROM control.sqlite_master').fetchone()
        for name in ['world.sqlite', 'control.sqlite']:
            source = readonly(run_path/name)
            target = sqlite3.connect(destination/name)
            try:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise EvidenceError('Snapshot database integrity failed')
            finally:
                target.close()
                source.close()
            checked((destination/name).read_bytes())
    finally:
        guard.close()


def ledger_view(store, agent):
    with store.connect() as db:
        db.execute('BEGIN')
        state = json.loads(db.execute('SELECT data FROM agents WHERE id=?', (agent,)).fetchone()['data'])
        requests = [dict(r) for r in db.execute('SELECT * FROM requests WHERE agent=? ORDER BY id', (agent,))]
        events = [dict(seq=r['seq'], kind=r['kind'], data=json.loads(r['data'])) for r in
                  db.execute('SELECT * FROM events WHERE agent=? ORDER BY seq', (agent,))]
        accounting = {'limits': [dict(r) for r in db.execute('SELECT * FROM limits ORDER BY name')],
                      'charged_or_held_micro_usd': db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM requests').fetchone()[0]}
    return {'checkpoint': state, 'requests': requests, 'trace': events, 'accounting': accounting}


class EvidenceSession:
    def __init__(self, store, agent, *, central=CENTRAL, action='resume', pause_when_waiting=False):
        try:
            self._initialize(store, agent, central=central, action=action, pause_when_waiting=pause_when_waiting)
        except Exception as exc:
            try:
                state = store.load(agent)
                write_new(Path(state['run_path'])/'baseline'/('EVIDENCE-FAILURE-'+uuid.uuid4().hex+'.json'),
                          encode({'boundary':'session_initialization', 'at_utc':now(),
                                  'error_type':type(exc).__name__, 'reproducibility':'incomplete'}))
            except Exception:
                pass  # A read-only run cannot hold a marker; the caller still gets an explicit failure.
            raise EvidenceError('Evidence initialization failed; run reproducibility is incomplete') from None

    def _initialize(self, store, agent, *, central, action, pause_when_waiting):
        self.store, self.agent, self.central = store, agent, Path(central)
        self.state = store.load(agent)
        self.run_path = Path(self.state['run_path'])
        self.root = self.central/'runs'/self.state['run_id']
        self.root.mkdir(parents=True, exist_ok=True)
        identity = {'run_id': self.state['run_id'], 'source_run_path': str(self.run_path)}
        origin = self.root/'ORIGIN.json'
        if origin.exists():
            if json.loads(origin.read_text()) != identity:
                raise EvidenceError('Archive run ID belongs to another original run')
        else:
            write_new(origin, encode(identity))
        self.source_id = source_snapshot(self.central)
        run_manifest = self.root/'RUN-MANIFEST.json'
        if not run_manifest.exists():
            raw = encode({'kind':'permanent-run-evidence-v1', **identity,
                'original_manifest':json.loads((self.run_path/'manifest.json').read_text()),
                'initial_source_snapshot':self.source_id, 'created_at_utc':now(),
                'layout':'Append-only sessions with sealed boundary captures; no prior session/result is overwritten'})
            write_new(run_manifest, raw)
            write_new(self.root/'RUN-MANIFEST.sha256', (sha(raw)+'  RUN-MANIFEST.json\n').encode())
            run_manifest.chmod(0o444)
        self.session_id = uuid.uuid4().hex
        self.folder = self.root/'sessions'/self.session_id
        self.folder.mkdir(parents=True, exist_ok=False)
        self.pause_when_waiting = pause_when_waiting
        self.capture_seconds = 0.0
        self.start = {'session_id': self.session_id, 'pid': os.getpid(), 'parent_pid': os.getppid(),
                      'started_at_utc': now(), 'action': action, 'source_snapshot': self.source_id,
                      'checkpoint_phase': self.state['phase'], 'model_turns': self.state['model_turns'],
                      'tool_calls': self.state['tool_calls']}
        write_new(self.folder/'START.json', encode(self.start))
        self.capture('session_start')

    def operation_clock(self):
        """Preservation I/O must not consume an agent's active-operation allowance."""
        return time.monotonic() - self.capture_seconds

    def capture(self, boundary, *, evaluation=None):
        started = time.monotonic()
        try:
            return self._capture(boundary, evaluation=evaluation)
        finally:
            self.capture_seconds += time.monotonic() - started

    def _capture(self, boundary, *, evaluation=None):
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid.uuid4().hex[:8]
        target = self.folder/'captures'/stamp
        target.mkdir(parents=True, exist_ok=False)
        try:
            view = ledger_view(self.store, self.agent)
            for name, value in view.items():
                write_new(target/(name+'.json'), encode(value))
            write_new(target/'run-manifest.json', (self.run_path/'manifest.json').read_bytes())
            database_pair(self.run_path, target)
            db = readonly(target/'world.sqlite')
            try:
                export = {}
                for table in ['metadata','people','documents','messages','tasks','decisions','effects','audit','briefs','brief_reads','submissions']:
                    export[table] = [dict(r) for r in db.execute('SELECT * FROM '+table)]
                write_new(target/'world-records.json', encode(export))
                for pub in export['briefs']:
                    write_new(target/f"publication-{pub['id']}-{pub['revision']}.md", pub['markdown'].encode())
            finally:
                db.close()
            log = self.run_path/'baseline/mcp-stderr.log'
            if log.exists():
                write_new(target/'mcp-stderr.log', log.read_bytes())
            if evaluation is not None:
                write_new(target/'evaluation.json', encode(evaluation))
            seal(target, {'kind': 'run-evidence-boundary', 'boundary': boundary, 'at_utc': now(),
                          'session_id': self.session_id, 'pid': os.getpid(), 'source_snapshot': self.source_id,
                          'model_requests_by_capture': 0, 'evaluation_included': evaluation is not None,
                          'capture_time_excluded_from_active_allowance':True,
                          'consistency': 'World/control locked together; ledger separately transaction-consistent'})
        except Exception as exc:
            write_new(self.run_path/'baseline'/('EVIDENCE-FAILURE-'+uuid.uuid4().hex+'.json'),
                      encode({'boundary': boundary, 'at_utc': now(), 'error_type': type(exc).__name__,
                              'reproducibility': 'incomplete', 'partial_capture': str(target)}))
            raise EvidenceError('Evidence preservation failed; run reproducibility is incomplete') from None
        return target

    def finish(self, reason, error_type=None):
        self.capture('session_exit')
        write_new(self.folder/'EXIT.json', encode({'session_id': self.session_id, 'pid': os.getpid(),
            'at_utc': now(), 'reason': reason, 'error_type': error_type,
            'capture_seconds_excluded_from_active_allowance':self.capture_seconds,
            'meaning': 'Python execution scope exited; parent process observation proves OS process termination'}))
        seal(self.folder, {'kind':'completed-process-session', 'session_id':self.session_id})


class ObservedStore:
    """Logging wrapper; preserves the original runner, provider payloads and allowances."""
    def __init__(self, store, session):
        self.base, self.session = store, session

    def __getattr__(self, name):
        return getattr(self.base, name)

    def save(self, agent, state, kind, details=None):
        self.base.save(agent, state, kind, details)
        self.session.capture(kind)
        if self.session.pause_when_waiting and kind == 'tool_result':
            db = readonly(self.session.run_path/'world.sqlite')
            try:
                messages = [json.loads(r['data']) for r in db.execute('SELECT data FROM messages')]
            finally:
                db.close()
            if all(any(m['sender']=='coordinator' and m['recipient']==p and m['topic']=='review_request'
                       for m in messages) for p in ['leo','nia']) and not any(m['topic']=='feedback' for m in messages):
                state.update(status='paused', stop_reason='restart_while_waiting')
                self.base.save(agent, state, 'paused', {'reason':'restart_while_waiting'})
                self.session.capture('waiting_restart_boundary')
                raise WaitingBoundary()

    def reserve(self, *args):
        result = self.base.reserve(*args)
        self.session.capture('model_reserved')
        return result

    def response(self, *args):
        result = self.base.response(*args)
        self.session.capture('model_response')
        return result


def process_observation(central, run_id, *, pid, returncode, action, started_at):
    folder = Path(central)/'runs'/run_id/'process-observations'
    path = folder/(uuid.uuid4().hex+'.json')
    raw = encode({'pid':pid, 'returncode':returncode,
        'action':action, 'started_at_utc':started_at, 'wait_returned_at_utc':now(),
        'observer_pid':os.getpid(), 'method':'subprocess.Popen + wait; actual OS child termination'})
    write_new(path, raw)
    write_new(path.with_suffix('.sha256'), (sha(raw)+'  '+path.name+'\n').encode())
    path.chmod(0o444)


def restart_errors(run_path, central=CENTRAL):
    root = Path(central)/'runs'/run_path.name
    origin = root/'ORIGIN.json'
    if not origin.exists() or json.loads(origin.read_text()).get('source_run_path') != str(run_path.resolve()):
        return ['missing_verified_waiting_process_restart']
    sessions = []
    for start in root.glob('sessions/*/START.json'):
        data = json.loads(start.read_text())
        if data['action'] in ['new','resume']:
            sessions.append((data, start.parent))
    sessions.sort(key=lambda pair:pair[0]['started_at_utc'])
    observations = [json.loads(p.read_text()) for p in root.glob('process-observations/*.json')]
    for (first, directory), (second, next_directory) in zip(sessions, sessions[1:]):
        if not (directory/'MANIFEST.json').exists():
            continue
        verify_tree(directory)
        waiting = [p for p in directory.glob('captures/*/MANIFEST.json') if json.loads(p.read_text())['boundary']=='waiting_restart_boundary']
        if not waiting:
            continue
        capture = waiting[-1].parent
        verify_tree(capture)
        checkpoint = json.loads((capture/'checkpoint.json').read_text())
        starts = [p.parent for p in next_directory.glob('captures/*/MANIFEST.json')
                  if json.loads(p.read_text())['boundary']=='session_start']
        if not starts:
            continue
        resumed = starts[0]
        verify_tree(resumed)
        same_checkpoint = json.loads((resumed/'checkpoint.json').read_text()) == checkpoint
        same_requests = json.loads((resumed/'requests.json').read_text()) == json.loads((capture/'requests.json').read_text())
        records = json.loads((capture/'world-records.json').read_text())
        messages = [json.loads(row['data']) for row in records['messages']]
        waiting_for_reviews = (all(any(m['sender']=='coordinator' and m['recipient']==p and m['topic']=='review_request'
                                     for m in messages) for p in ['leo','nia'])
                               and not any(m['topic']=='feedback' for m in messages))
        if (first['pid'] != second['pid'] and second['action']=='resume'
                and same_checkpoint and same_requests and waiting_for_reviews
                and any(o['pid']==first['pid'] and o['returncode']==0
                        and o['wait_returned_at_utc']<=second['started_at_utc'] for o in observations)):
            return []
    return ['missing_verified_waiting_process_restart']
