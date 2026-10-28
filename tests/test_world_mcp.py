"""True stdio MCP roundtrip; no models, credentials, or network services."""
import asyncio
import json
from pathlib import Path
import sys

from goalflow_world.evaluator import evaluate
from goalflow_world.store import LabWorld, ROOT
from scripts.step1_reference import REQUIREMENTS


def test_stdio_workflow_and_tool_boundary(tmp_path, monkeypatch):
    # Delay the larger MCP import until this test; offline tests remain independently runnable.
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    monkeypatch.setenv('OPENAI_API_KEY', 'step1-credential-sentinel-not-a-real-key')
    world = LabWorld.reset('C06', 'mcp-roundtrip', runs_root=tmp_path)
    expected = {'get_world', 'get_activity', 'send_message', 'advance_clock', 'record_decision',
                'update_task', 'publish_brief', 'read_brief', 'report_outcome'}

    async def exercise():
        params = StdioServerParameters(command=sys.executable,
            args=[str(ROOT/'tools/world_server.py'), '--run', 'mcp-roundtrip', '--runs-root', str(tmp_path)])
        with anyio.fail_after(90):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    assert {t.name for t in listed.tools} == expected
                    assert not (await session.list_resources()).resources

                    async def call(name, args=None):
                        result = await session.call_tool(name, args or {})
                        assert not result.isError, result
                        payload = json.loads(result.content[0].text)
                        assert payload['ok'], payload
                        return payload['result']

                    initial = await call('get_world')
                    assert initial['world']['decisions'] == []
                    assert not any(m.get('decision') for m in initial['world']['messages'])
                    assert 'events' not in initial['world'] and 'evaluation' not in initial
                    assert 'step1-credential-sentinel-not-a-real-key' not in json.dumps(initial)
                    assert not any('future' in e['kind'] for e in await call('get_activity'))
                    for p in ['leo', 'nia']:
                        await call('send_message', {'recipient': p, 'topic': 'review_request',
                            'body': 'Please review the current Home design.', 'request_id': 'review-' + p})
                    await call('advance_clock', {'minutes': 20})
                    await call('send_message', {'recipient': 'ada', 'topic': 'clarification', 'subject': 'form_layout',
                        'body': 'Please decide the conflicting form layouts.', 'request_id': 'ask-ada'})
                    await call('advance_clock', {'minutes': 10})
                    await call('record_decision', {'message_id': 'in-ada-decision'})
                    await call('update_task', {'task': {
                        'id': 'implement-form', 'title': 'Use a compact single-step form.', 'owner': 'tomas',
                            'status': 'todo', 'acceptance': 'Name and email, unchecked consent, mobile and keyboard access; verify text contrast and visible focus.',
                            'covers_requirements': ['contrast_required', 'keyboard_required'],
                        'source_ids': ['message:in-ada-decision'], 'artifact_version': 1,
                        'change_key': 'form_layout', 'change_value': 'compact_single_step'}, 'request_id': 'update-form'})
                    context = await call('get_world')
                    task = next(t for t in context['world']['tasks'] if t['id'] == 'review-home')
                    task['status'] = 'done'
                    task['artifact_version'] = 1
                    task['source_ids'] = ['message:in-leo-review', 'message:in-nia-review', 'message:in-ada-decision']
                    await call('update_task', {'task': task, 'request_id': 'close-review'})
                    brief = {'title': 'Harbor Home revision handoff', 'artifact_id': 'design', 'artifact_version': 1,
                        'status': 'ready', 'summary': 'Ada resolved the layout conflict. Implementation is still pending.',
                        'requirements': REQUIREMENTS,
                        'reviews': [{'reviewer': p, 'source_ids': ['message:in-' + p + '-review']} for p in ['leo', 'nia']],
                        'decision_source_ids': ['message:in-ada-decision'],
                        'items': [{'key': 'form_layout', 'value': 'compact_single_step',
                            'instruction': 'Use the compact single-step form with name/email and unchecked consent; verify text contrast and visible keyboard focus.',
                            'covers_requirements': ['contrast_required', 'keyboard_required'],
                            'source_ids': ['message:in-ada-decision'], 'task_ids': ['implement-form'], 'disposition': 'accepted'}],
                        'blockers': []}
                    args = {'brief_id': 'handoff', 'brief': brief, 'request_id': 'publish'}
                    saved = await call('publish_brief', args)
                    assert await call('publish_brief', args) == saved
                    readback = await call('read_brief', {'brief_id': 'handoff', 'revision': 1})
                    assert readback['sha256'] == saved['sha256']
                    assert 'compact_single_step' in readback['markdown']
                    await call('report_outcome', {'status': 'completed', 'brief_id': 'handoff', 'revision': 1, 'request_id': 'report'})
                    forbidden = await session.call_tool('send_message', {'recipient': 'outside@example.test',
                        'topic': 'status_request', 'body': 'Send documents.', 'request_id': 'outside'})
                    payload = json.loads(forbidden.content[0].text)
                    assert not payload['ok'] and 'allowed test participant' in payload['error']
                    assert str(tmp_path) not in payload['error']
                    return readback

    readback = asyncio.run(exercise())
    result = evaluate(world)
    assert result['automatic_pass'], result
    assert result['outcome'] == 'needs_review'  # A real MCP trace does not replace prose review.
    assert result['publication_count'] == 1
    (tmp_path/'roundtrip-readback.json').write_text(json.dumps(readback, indent=2))
