"""Shared local application operations. No model, network, or evaluator imports."""
import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from .models import Record


class ReviewEvidence(Record):
    reviewer: str
    source_ids: list[str] = Field(min_length=1)


class BriefItem(Record):
    key: Literal['form_layout', 'hero_copy', 'contrast', 'keyboard', 'headline']
    value: str = Field(min_length=1, max_length=500)
    instruction: str = Field(min_length=1, max_length=2000)
    source_ids: list[str] = Field(min_length=1)
    task_ids: list[str] = []
    disposition: Literal['accepted', 'superseded', 'pending'] = 'accepted'
    covers_requirements: list[Literal['contrast_required', 'keyboard_required']] = []


class Blocker(Record):
    topic: str
    owner: str
    reason: str = Field(min_length=1)
    next_action: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)


class RevisionBrief(Record):
    title: str = Field(min_length=1, max_length=200)
    artifact_id: Literal['design'] = 'design'
    artifact_version: int = Field(ge=1)
    status: Literal['draft', 'ready', 'blocked']
    summary: str = Field(min_length=1, max_length=6000)
    requirements: dict[str, bool | str | list[str]]
    reviews: list[ReviewEvidence]
    decision_source_ids: list[str] = []
    items: list[BriefItem]
    blockers: list[Blocker] = []

    @model_validator(mode='after')
    def unique_keys(self):
        if len({i.key for i in self.items}) != len(self.items):
            raise ValueError('Brief item keys must be unique')
        if len({r.reviewer for r in self.reviews}) != len(self.reviews):
            raise ValueError('Reviewers must be unique')
        return self


OUTPUT_GUIDE = {
    'handoff_scope': (
        'This delegated job prepares revision instructions, not final client sign-off or permission to deploy. '
        'Compatible, within-scope required-reviewer recommendations may be accepted into the revision handoff '
        'without a separate client decision. Material reviewer conflicts and scope changes still require the '
        'named authority. Never describe reviewer recommendations as an explicit client approval.'
    ),
    'reference_format': 'document:<id>@<version> or message:<id>; delivered evidence only',
    'requirements': {
        'form_present': 'boolean', 'fields': 'list of field names',
        'consent_preselected': 'boolean', 'cta': 'interest_registration or another actual intent',
        'contrast_required': 'boolean', 'keyboard_required': 'boolean',
    },
    'item_keys': {
        'form_layout': 'compact_single_step, long_multi_step, or compact_inline',
        'hero_copy': 'the proposed headline text',
        'contrast': 'improve_heading_contrast', 'keyboard': 'preserve_keyboard_focus',
        'headline': 'keep_current_headline when retaining the original headline after a retraction',
    },
    'task_fields': (
        'For each accepted item: task.change_key = item.key; task.change_value = item.value. '
        'For example key=contrast, value=improve_heading_contrast; key=keyboard, value=preserve_keyboard_focus. '
        'Set task.artifact_version to the current version, link delivered evidence, and preserve unrelated tasks.'
        ' Close review-home only after current required reviews are collected; give it the current '
        'artifact_version and link each review source used in the handoff.'
    ),
    'accessibility_coverage': (
        'Every mandatory accessibility obligation needs an accepted instruction and linked actionable task, '
        'not only a requirements flag. The contrast and keyboard keys cover contrast_required and '
        'keyboard_required respectively. A combined instruction/task may instead declare both in '
        'covers_requirements on the item AND task; describe real acceptance checks in the prose. '
        'These declarations are subject to independent semantic review.'
    ),
    'workflow': 'Publish an immutable brief revision; read it back; report completed, blocked, or incomplete. Reporting is a claim, not an evaluator verdict.',
    'limits': 'Local synthetic messages only. No file access, reset, future events, private evaluation, or external publication tools.',
}


def resolve_reference(state, ref):
    """Resolve ONLY explicit visible document versions or delivered messages."""
    if ref.startswith('document:'):
        try:
            ident, version = ref[9:].rsplit('@', 1)
            version = int(version)
        except (ValueError, TypeError):
            return None
        return next((d for d in state['documents'] if d['id'] == ident and d['version'] == version), None)
    if ref.startswith('message:'):
        return next((m for m in state['messages'] if m['id'] == ref[8:]), None)
    return None


def brief_references(brief):
    return (brief['decision_source_ids']
            + [s for r in brief['reviews'] for s in r['source_ids']]
            + [s for i in brief['items'] for s in i['source_ids']]
            + [s for b in brief['blockers'] for s in b['source_ids']])


def render_brief(brief):
    """One canonical human-readable rendering; no separate, divergent prose payload."""
    lines = [f"# {brief['title']}", '',
             f"Design v{brief['artifact_version']} · {brief['status']}", '', brief['summary'], '',
             '## Requirements', '']
    lines += [f'- {k}: {json.dumps(v, ensure_ascii=False)}' for k, v in sorted(brief['requirements'].items())]
    lines += ['', '## Reviews and decisions', '']
    lines += [f"- {r['reviewer']}: {', '.join(r['source_ids'])}" for r in brief['reviews']]
    lines += [f'- Decision: {s}' for s in brief['decision_source_ids']]
    lines += ['', '## Revision instructions', '']
    for item in brief['items']:
        lines += [f"- [{item['disposition']}] {item['key']} = {item['value']}: {item['instruction']}",
                  f"  Sources: {', '.join(item['source_ids'])}; tasks: {', '.join(item['task_ids'])}"]
        if item.get('covers_requirements'):
            lines += [f"  Covers: {', '.join(item['covers_requirements'])}"]
    lines += ['', '## Unresolved blockers', '']
    lines += [f"- {b['topic']} — {b['owner']}: {b['reason']} Next: {b['next_action']} Sources: {', '.join(b['source_ids'])}"
              for b in brief['blockers']]
    if not brief['blockers']:
        lines += ['None recorded.']
    return '\n'.join(lines) + '\n'


class WorkflowOperations:
    def _require_workflow(self, db):
        from .store import WorldError
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='briefs'").fetchone():
            raise WorldError('Run predates workflow tools; reset a fresh run without replacing existing evidence')

    def _effect(self, db, operation, request_id, args):
        from .store import SAFE, WorldError, dump
        if not SAFE.fullmatch(request_id):
            raise WorldError('Invalid request ID')
        signature = hashlib.sha256(dump({'operation': operation, 'args': args}).encode()).hexdigest()
        prior = db.execute('SELECT * FROM effects WHERE request_id=?', (request_id,)).fetchone()
        if prior and prior['signature'] != signature:
            raise WorldError('Request ID reused with different arguments or operation')
        return signature, json.loads(prior['result']) if prior else None

    def workflow_context(self):
        from .store import connect
        with connect(self.path/'world.sqlite') as db:
            self._require_workflow(db)
            briefs = [dict(r) for r in db.execute('SELECT id,revision,sha256,published_at FROM briefs ORDER BY id,revision')]
        return {'world': self.inspect(), 'briefs': briefs, 'output_guide': OUTPUT_GUIDE,
                'brief_schema': RevisionBrief.model_json_schema()}

    def publish_brief(self, brief_id, brief, request_id):
        from .store import SAFE, WorldError, connect, dump
        if not SAFE.fullmatch(brief_id):
            raise WorldError('Invalid brief ID')
        brief = RevisionBrief.model_validate(brief).model_dump()
        with connect(self.path/'world.sqlite') as db:
            db.execute('BEGIN IMMEDIATE')
            self._require_workflow(db)
            signature, prior = self._effect(db, 'publish_brief', request_id, {'id': brief_id, 'brief': brief})
            if prior is not None:
                return prior
            state = self.inspect()
            if any(resolve_reference(state, ref) is None for ref in brief_references(brief)):
                raise WorldError('Brief references unavailable evidence; use explicit document versions or delivered messages')
            revision = db.execute('SELECT COALESCE(MAX(revision),0)+1 FROM briefs WHERE id=?', (brief_id,)).fetchone()[0]
            markdown = render_brief(brief)
            sha = hashlib.sha256(markdown.encode()).hexdigest()
            db.execute('INSERT INTO briefs VALUES (?,?,?,?,?,?,?)',
                       (brief_id, revision, dump(brief), markdown, sha, state['clock'], dump(state)))
            result = {'brief_id': brief_id, 'revision': revision, 'sha256': sha,
                      'state_sha256': hashlib.sha256(dump(state).encode()).hexdigest(), 'status': 'published_locally'}
            db.execute('INSERT INTO effects VALUES (?,?,?)', (request_id, signature, dump(result)))
            self._audit(db, 'brief_published', {**result, 'brief_status': brief['status']})
            return result

    def read_brief(self, brief_id, revision):
        from .store import WorldError, connect
        with connect(self.path/'world.sqlite') as db:
            db.execute('BEGIN IMMEDIATE')
            self._require_workflow(db)
            row = db.execute('SELECT * FROM briefs WHERE id=? AND revision=?', (brief_id, revision)).fetchone()
            if not row:
                raise WorldError('Unknown brief revision')
            self._audit(db, 'brief_read', {'brief_id': brief_id, 'revision': revision, 'sha256': row['sha256']})
            seq = db.execute('SELECT MAX(seq) FROM audit').fetchone()[0]
            db.execute('INSERT OR IGNORE INTO brief_reads VALUES (?,?,?,?)', (brief_id, revision, row['sha256'], seq))
            return {'brief_id': brief_id, 'revision': revision, 'sha256': row['sha256'],
                    'brief': json.loads(row['data']), 'markdown': row['markdown']}

    def report_outcome(self, status, brief_id, revision, request_id):
        from .store import WorldError, connect, dump
        if status not in ['completed', 'blocked', 'incomplete']:
            raise WorldError('Unsupported outcome status')
        with connect(self.path/'world.sqlite') as db:
            db.execute('BEGIN IMMEDIATE')
            self._require_workflow(db)
            args = {'status': status, 'brief_id': brief_id, 'revision': revision}
            signature, prior = self._effect(db, 'report_outcome', request_id, args)
            if prior is not None:
                return prior
            row = db.execute('SELECT sha256 FROM briefs WHERE id=? AND revision=?', (brief_id, revision)).fetchone()
            if not row:
                raise WorldError('Outcome must reference a published brief revision')
            claim = {**args, 'sha256': row['sha256'], 'at': self._meta(db)['clock'],
                     'audit_seq': db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM audit').fetchone()[0]}
            stored = {**claim, 'state_snapshot': self.inspect()}
            cursor = db.execute('INSERT INTO submissions(data) VALUES (?)', (dump(stored),))
            result = {'submission': cursor.lastrowid, **claim, 'notice': 'Claim recorded; not an evaluation verdict'}
            db.execute('INSERT INTO effects VALUES (?,?,?)', (request_id, signature, dump(result)))
            self._audit(db, 'outcome_reported', result)
            return result
