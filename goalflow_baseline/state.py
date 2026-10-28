"""Atomic checkpoints and conservative shared spend reservations (integer micro-USD)."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


class LimitReached(ValueError):
    pass


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


class StateStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, agent TEXT NOT NULL, reserved INTEGER NOT NULL,
                    input_bound INTEGER NOT NULL, output_cap INTEGER NOT NULL,
                    actual INTEGER, input_tokens INTEGER, output_tokens INTEGER,
                    status TEXT NOT NULL, scope TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS limits (name TEXT PRIMARY KEY, amount INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT NOT NULL,
                    kind TEXT NOT NULL, data TEXT NOT NULL
                );
            ''')
        self.path.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def _event(self, db, agent, kind, data):
        db.execute('INSERT INTO events(agent,kind,data) VALUES (?,?,?)',
                   (agent, kind, encode({'at_utc': datetime.now(timezone.utc).isoformat(), **data})))

    def create(self, agent, state):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            cfg = state['config']
            scope = cfg.get('scope', 'step2')
            if scope not in ['step2', 'discovery']:
                raise LimitReached('Unknown experiment allowance scope')
            for name, amount in [('study', cfg['study_micro_usd']), (scope, cfg[scope + '_micro_usd'])]:
                db.execute('INSERT OR IGNORE INTO limits VALUES (?,?)', (name, amount))
                if db.execute('SELECT amount FROM limits WHERE name=?', (name,)).fetchone()[0] != amount:
                    raise LimitReached('Stored shared budget differs; do not silently change study limits')
            others = [json.loads(r['data']) for r in db.execute('SELECT data FROM agents')]
            scoped = [s for s in others if s['config'].get('scope', 'step2') == scope]
            if len(scoped) >= cfg['max_' + scope + '_attempts']:
                raise LimitReached(scope + ' attempt allowance exhausted')
            if scope == 'discovery':
                case = state.get('case_id')
                if case not in cfg['case_attempts']:
                    raise LimitReached('Case is outside the frozen discovery matrix')
                if sum(s.get('case_id') == case for s in scoped) >= cfg['case_attempts'][case]:
                    raise LimitReached('Discovery case attempt allowance exhausted')
            db.execute('INSERT INTO agents VALUES (?,?)', (agent, encode(state)))
            self._event(db, agent, 'created', {'purpose': scope, 'fingerprint': state['fingerprint']})

    def load(self, agent):
        with self.connect() as db:
            row = db.execute('SELECT data FROM agents WHERE id=?', (agent,)).fetchone()
            if not row:
                raise ValueError('No baseline checkpoint for this run')
            return json.loads(row['data'])

    def save(self, agent, state, kind, details=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE agents SET data=? WHERE id=?', (encode(state), agent))
            self._event(db, agent, kind, details or {})

    def reserve(self, agent, state, input_bound):
        cfg = state['config']
        scope = cfg.get('scope', 'step2')
        request_id = agent + '-m' + str(state['model_turns'] + 1)
        cost = input_bound * cfg['input_micro_usd_per_token'] + cfg['max_output_tokens'] * cfg['output_micro_usd_per_token']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for account in ['study', scope]:
                total = db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM requests' +
                                   (' WHERE scope=?' if account != 'study' else ''),
                                   (scope,) if account != 'study' else ()).fetchone()[0]
                cap = db.execute('SELECT amount FROM limits WHERE name=?', (account,)).fetchone()[0]
                if total + cost > cap:
                    raise LimitReached(account + ' budget reservation would exceed its ceiling')
            used = db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM requests WHERE agent=?', (agent,)).fetchone()[0]
            if used + cost > cfg['max_run_micro_usd']:
                raise LimitReached('Run budget reservation would exceed its ceiling')
            if state['input_tokens'] + state['output_tokens'] + input_bound + cfg['max_output_tokens'] > cfg['max_total_tokens']:
                raise LimitReached('Token reservation would exceed the run ceiling')
            state.update(phase='model_inflight', request_id=request_id, model_turns=state['model_turns'] + 1)
            db.execute('INSERT INTO requests VALUES (?,?,?,?,?,NULL,NULL,NULL,?,?)',
                       (request_id, agent, cost, input_bound, cfg['max_output_tokens'], 'reserved', scope))
            db.execute('UPDATE agents SET data=? WHERE id=?', (encode(state), agent))
            self._event(db, agent, 'model_reserved', {'request_id': request_id, 'reserved_micro_usd': cost, 'input_bound': input_bound})
        return request_id

    def response(self, agent, state, output, input_tokens, output_tokens, meta):
        cfg = state['config']
        actual = input_tokens * cfg['input_micro_usd_per_token'] + output_tokens * cfg['output_micro_usd_per_token']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM requests WHERE id=?', (state['request_id'],)).fetchone()
            overrun = input_tokens > row['input_bound'] or output_tokens > row['output_cap']
            state['history'].extend(output)
            state['pending'] = [dict(item) for item in output if item['type'] == 'function_call']
            state['input_tokens'] += input_tokens
            state['output_tokens'] += output_tokens
            state['phase'] = 'response_ready'
            state['reported_model'] = meta.get('model')
            if overrun:
                state.update(status='stopped', stop_reason='provider_usage_exceeded_reservation')
            elif meta.get('status') != 'completed':
                state.update(status='stopped', stop_reason='incomplete_model_response')
            db.execute('UPDATE requests SET actual=?,input_tokens=?,output_tokens=?,status=? WHERE id=?',
                       (actual, input_tokens, output_tokens, 'settled', state['request_id']))
            db.execute('UPDATE agents SET data=? WHERE id=?', (encode(state), agent))
            self._event(db, agent, 'model_response', {'request_id': state['request_id'], 'output': output,
                'input_tokens': input_tokens, 'output_tokens': output_tokens, 'estimated_micro_usd': actual, **meta})

    def summary(self, agent):
        state = self.load(agent)
        with self.connect() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM requests WHERE agent=? ORDER BY id', (agent,))]
        return {'run_id': state['run_id'], 'status': state['status'], 'stop_reason': state.get('stop_reason'),
                'phase': state['phase'], 'model': state['config']['model'], 'reported_model': state.get('reported_model'),
                'model_turns': state['model_turns'], 'tool_calls': state['tool_calls'],
                'input_tokens': state['input_tokens'], 'output_tokens': state['output_tokens'],
                'estimated_cost_usd': sum(r['actual'] or 0 for r in rows) / 1_000_000,
                'held_or_uncertain_usd': sum(r['reserved'] for r in rows if r['actual'] is None) / 1_000_000,
                'active_seconds': round(state['active_seconds'], 3), 'fingerprint': state['fingerprint'],
                'purpose': state['config'].get('scope', 'step2'), 'requests': rows}

    def export(self, agent):
        state = self.load(agent)
        folder = Path(state['run_path'])/'baseline'
        folder.mkdir(exist_ok=True)
        with self.connect() as db:
            events = [dict(seq=r['seq'], kind=r['kind'], data=json.loads(r['data']))
                      for r in db.execute('SELECT * FROM events WHERE agent=? ORDER BY seq', (agent,))]
        for name, value in [('checkpoint.json', state), ('summary.json', self.summary(agent)), ('trace.json', events)]:
            path = folder/name
            path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
            path.chmod(0o600)
        return folder
