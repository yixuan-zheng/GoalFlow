"""Hand-authored operator reference executions, NOT an agent or a baseline.

These do not read scoring contracts. They exercise application tools using visible
records and explicit reference instructions. Their reviews are fixture attestations,
never human-review results for experimental agent runs.
"""
from goalflow_world.store import LabWorld


REQUIREMENTS = {
    'form_present': True, 'fields': ['name', 'email'], 'consent_preselected': False,
    'cta': 'interest_registration', 'contrast_required': True, 'keyboard_required': True,
}


def prepare_reference(world):
    case = base_case(world.inspect()['case_id'])
    for reviewer in ['leo', 'nia']:
        world.send_message(reviewer, 'review_request', 'Please review the current Home design.', 'review-' + reviewer)
    world.advance(20)
    if case == 'R01':
        world = LabWorld(world.path)
    if case == 'C04':
        world.advance(40)
        world.send_message('nia', 'reminder', 'Please send the required review.', 'remind-nia')
        world.advance(15)
    if case in ['C06', 'C05DEV', 'VBLOCK']:
        world.send_message('ada', 'clarification', 'Please resolve Leo and Nia’s form layout disagreement.',
                           'ask-layout', subject='form_layout')
        if case == 'VBLOCK':
            world.advance(940)
        else:
            world.advance(10)
            if case == 'C05DEV':
                for reviewer in ['leo', 'nia']:
                    world.send_message(reviewer, 'review_request', 'Please review revision 2.', 'v2-' + reviewer, 2)
                world.send_message('ada', 'clarification', 'Please decide the revision 2 layout.', 'v2-layout', 2, 'form_layout')
                world.advance(12)
                world.record_decision('in-ada-v2')
            else:
                world.record_decision('in-ada-decision')
    if case == 'C07DEV':
        world.advance(15)
    return assemble_reference(world)


def base_case(case):
    return {'C04V2': 'C04', 'C06V2': 'C06', 'C05DEVV2': 'C05DEV',
            'C07DEVV2': 'C07DEV', 'R01V2': 'R01'}.get(case, case)


def assemble_reference(world, *, case=None):
    """Author a known-answer artifact from already-delivered evidence, without waiting."""
    case = case or base_case(world.inspect()['case_id'])
    state = world.inspect()
    version = state['current_artifact_version']
    sources = {p: 'message:' + next(m['id'] for m in reversed(state['messages'])
               if m['sender'] == p and m['topic'] == 'feedback' and m['artifact_version'] == version)
               for p in ['leo', 'nia']}
    decision_refs = ['message:' + d['source_id'] for d in state['decisions'] if d['artifact_version'] == version]
    brief = {
        'title': 'Harbor Home — implementation revision brief', 'artifact_id': 'design',
        'artifact_version': version, 'status': 'blocked' if case == 'VBLOCK' else 'ready',
        'summary': 'Review handoff only; website implementation has not been completed.',
        'requirements': dict(REQUIREMENTS),
        'reviews': [{'reviewer': p, 'source_ids': [sources[p]]} for p in ['leo', 'nia']],
        'decision_source_ids': decision_refs, 'items': [], 'blockers': [],
    }
    if case == 'VBLOCK':
        brief['summary'] += ' Layout remains undecided; do not treat this draft as an approved handoff.'
        brief['blockers'] = [{'topic': 'form_layout', 'owner': 'ada',
            'reason': 'Required layout decision has not arrived by the test horizon.',
            'next_action': 'Escalate to Mira to obtain Ada’s decision or an authorized replacement; keep implementation blocked.',
            'source_ids': [sources['leo'], sources['nia'], 'document:policy@1']}]
        return brief

    def add(key, value, instruction, refs, task_id):
        brief['items'].append({'key': key, 'value': value, 'instruction': instruction,
                              'source_ids': refs, 'task_ids': [task_id], 'disposition': 'accepted', 'covers_requirements': []})
        world.upsert_task({'id': task_id, 'title': instruction, 'owner': 'tomas', 'status': 'todo',
                          'acceptance': instruction + ' Preserve name/email, unchecked consent and keyboard access.',
                          'source_ids': refs, 'artifact_version': version, 'change_key': key, 'change_value': value},
                         request_id='task-' + task_id)

    layout = 'compact_inline' if case == 'C05DEV' else 'compact_single_step'
    layout_refs = decision_refs or [sources['leo'], sources['nia']]
    add('form_layout', layout, 'Use the compact inline form.' if version == 2 else 'Use a compact single-step form.',
        layout_refs, 'implement-form')
    if case in ['C01', 'C01V2', 'C04', 'R01']:
        add('hero_copy', 'Evening learning, at your pace.', 'Set the hero headline to “Evening learning, at your pace.”',
            [sources['leo']], 'revise-headline')
    if case == 'C07DEV':
        add('headline', 'keep_current_headline', 'Retain “Find your next step.”; the earlier headline request is withdrawn.',
            ['message:in-leo-retraction', 'document:design@1'], 'retain-headline')
    add('contrast', 'improve_heading_contrast', 'Verify workshop-card text contrast on desktop and mobile; correct insufficient contrast.',
        ['document:brief@1', sources['nia']], 'verify-contrast')
    add('keyboard', 'preserve_keyboard_focus', 'Verify visible focus and keyboard order for CTA, form controls, consent and submission.',
        ['document:brief@1', 'document:design@' + str(version)], 'verify-keyboard')
    task = next(t for t in state['tasks'] if t['id'] == 'review-home')
    task.update(status='done', source_ids=list(sources.values()) + decision_refs, artifact_version=version)
    world.upsert_task(task, request_id='review-collected')
    return brief


def publish_reference(world, brief, *, prefix='reference', read=True, report=True):
    saved = world.publish_brief('handoff', brief, prefix + '-publish')
    if read:
        world.read_brief('handoff', saved['revision'])
    if report:
        world.report_outcome('blocked' if brief['status'] == 'blocked' else 'completed',
                             'handoff', saved['revision'], prefix + '-report')
    return saved


def reference_review(saved):
    return {'brief_sha256': saved['sha256'], 'reviewer_kind': 'reference_fixture',
            'state_sha256': saved['state_sha256'],
            'reviewer': 'step1-reference-author',
            'notes': 'Known-answer reference artifact authored for scorer validation, not an experimental human review.',
            'requirements_covered': True, 'decisions_faithful': True,
            'claims_supported': True, 'tasks_actionable': True}
