"""Offline controller tests; scripted providers are NOT experimental model results."""
import asyncio
import copy
import json

import pytest

from goalflow_baseline.bridge import ALLOWED_TOOLS, connect_world
from goalflow_baseline.runner import Runner, new_state
from goalflow_baseline.state import LimitReached, StateStore, digest
from goalflow_world.store import LabWorld, ROOT, WorldError


def response(name=None, args=None, call_id='call-one', **overrides):
    value = {'id': 'mock-response', 'model': 'gpt-5.6-terra', 'status': 'completed',
             'usage': {'input_tokens': 20, 'output_tokens': 10}, 'output': []}
    if name:
        value['output'] = [{'type': 'reasoning', 'id': 'reasoning-one', 'summary': [], 'encrypted_content': 'fixture-opaque-item'},
                           {'type': 'function_call', 'name': name, 'arguments': json.dumps(args or {}), 'call_id': call_id}]
    value.update(overrides)
    return value


class ScriptedProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []

    async def create(self, payload, timeout):
        self.payloads.append(copy.deepcopy(payload))
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class LocalBridge:
    tools = [{'type': 'function', 'name': name, 'parameters': {'type': 'object', 'properties': {}}, 'strict': False}
             for name in sorted(ALLOWED_TOOLS)]

    def __init__(self, world, lose_clock_reply=False):
        self.world = world
        self.lose_clock_reply = lose_clock_reply
        self.calls = []

    async def call(self, name, args):
        self.calls.append((name, copy.deepcopy(args)))
        if name == 'get_world':
            value = self.world.workflow_context()
        elif name == 'get_activity':
            value = self.world.timeline()
        elif name == 'advance_clock':
            value = self.world.advance(**args)
            if self.lose_clock_reply:
                self.lose_clock_reply = False
                raise ConnectionError('Synthetic lost acknowledgement after commit')
        else:
            raise AssertionError('Unexpected local test operation')
        return {'ok': True, 'result': value}


def setup(tmp_path, **limits):
    world = LabWorld.reset('C01', 'baseline-test', runs_root=tmp_path/'runs')
    bridge = LocalBridge(world)
    config = json.loads((ROOT/'config/baseline.json').read_text())
    config.update(limits)
    store = StateStore(tmp_path/'ledger.sqlite')
    agent = digest(str(world.path))[:24]
    store.create(agent, new_state(world.path, config, bridge.tools))
    return world, bridge, store, agent


def test_resume_after_tool_effect_commits_and_reply_is_lost(tmp_path):
    world, bridge, store, agent = setup(tmp_path)
    bridge.lose_clock_reply = True
    provider = ScriptedProvider([response('advance_clock', {'minutes': 10})])
    result = asyncio.run(Runner(store, agent, bridge, provider).run())
    assert result['stop_reason'] == 'tool_transport_uncertain'
    assert world.inspect()['clock'].endswith('09:10:00-04:00')
    next_provider = ScriptedProvider([response()])
    resumed = asyncio.run(Runner(store, agent, LocalBridge(LabWorld(world.path)), next_provider).run())
    assert world.inspect()['clock'].endswith('09:10:00-04:00')
    assert resumed['model_turns'] == 2
    history = store.load(agent)['history']
    assert sum(item.get('type') == 'function_call_output' for item in history) == 1
    assert any(item.get('type') == 'reasoning' for item in next_provider.payloads[0]['input'])
    assert next_provider.payloads[0]['store'] is False
    assert next_provider.payloads[0]['parallel_tool_calls'] is False


def test_checkpoint_pause_and_fresh_runner_resume_without_hint(tmp_path):
    world, bridge, store, agent = setup(tmp_path)
    unused = ScriptedProvider([])
    paused = asyncio.run(Runner(store, agent, bridge, unused).run(pause_after_tools=1))
    assert paused['status'] == 'paused' and not unused.payloads
    provider = ScriptedProvider([response('get_activity'), response()])
    asyncio.run(Runner(store, agent, LocalBridge(world), provider).run())
    assert len(store.load(agent)['history']) == 4
    assert store.summary(agent)['tool_calls'] == 2


@pytest.mark.parametrize('limit,value', [('max_model_turns', 1), ('max_tool_calls', 1),
                                        ('max_run_micro_usd', 1), ('max_total_tokens', 1), ('max_active_seconds', 0)])
def test_limits_stop_before_excess_provider_or_tool_use(tmp_path, limit, value):
    world, bridge, store, agent = setup(tmp_path, **{limit: value})
    provider = ScriptedProvider([response('get_activity'), response()])
    result = asyncio.run(Runner(store, agent, bridge, provider).run())
    assert result['status'] == 'stopped'
    assert len(provider.payloads) <= (1 if limit == 'max_model_turns' else 0)
    assert result['model_turns'] <= 1


def test_provider_error_holds_reservation_and_does_not_log_error_body(tmp_path):
    _, bridge, store, agent = setup(tmp_path)
    sentinel = 'SECRET-AUTHORIZATION-SENTINEL'
    provider = ScriptedProvider([RuntimeError('Bearer ' + sentinel)])
    result = asyncio.run(Runner(store, agent, bridge, provider).run())
    assert result['stop_reason'] == 'model_request_uncertain'
    assert result['held_or_uncertain_usd'] > 0 and result['estimated_cost_usd'] == 0
    folder = store.export(agent)
    assert all(sentinel not in p.read_text() for p in folder.glob('*.json'))
    asyncio.run(Runner(store, agent, bridge, provider).run())
    assert len(provider.payloads) == 1


def test_process_loss_during_model_call_is_not_silently_retried(tmp_path):
    class PowerLoss(BaseException):
        pass
    _, bridge, store, agent = setup(tmp_path)
    with pytest.raises(PowerLoss):
        asyncio.run(Runner(store, agent, bridge, ScriptedProvider([PowerLoss()])).run())
    assert store.load(agent)['phase'] == 'model_inflight'
    provider = ScriptedProvider([])
    result = asyncio.run(Runner(store, agent, bridge, provider).run())
    assert result['stop_reason'] == 'model_request_uncertain_after_restart'
    assert not provider.payloads and result['held_or_uncertain_usd'] > 0


def test_incomplete_model_output_is_charged_but_not_executed(tmp_path):
    _, bridge, store, agent = setup(tmp_path)
    provider = ScriptedProvider([response('advance_clock', {'minutes': 10}, status='incomplete')])
    result = asyncio.run(Runner(store, agent, bridge, provider).run())
    assert result['stop_reason'] == 'incomplete_model_response'
    assert len(bridge.calls) == 1 and result['estimated_cost_usd'] > 0


def test_unknown_tool_cannot_dispatch_arbitrary_operations(tmp_path):
    _, bridge, store, agent = setup(tmp_path)
    provider = ScriptedProvider([response('read_file', {'path': '.env'}), response()])
    asyncio.run(Runner(store, agent, bridge, provider).run())
    assert [name for name, args in bridge.calls] == ['get_world']
    assert any('Tool is not allowed' in item.get('output', '') for item in store.load(agent)['history'])


def test_changed_baseline_fingerprint_refuses_resume(tmp_path):
    _, bridge, store, agent = setup(tmp_path)
    state = store.load(agent)
    state['fingerprint'] = 'different'
    store.save(agent, state, 'test-change')
    with pytest.raises(ValueError, match='changed'):
        asyncio.run(Runner(store, agent, bridge, ScriptedProvider([])).run())


def test_shared_budget_is_reserved_atomically_across_attempts(tmp_path):
    world, bridge, store, agent = setup(tmp_path, study_micro_usd=100000, step2_micro_usd=100000, max_step2_attempts=2)
    state = store.load(agent)
    store.reserve(agent, state, 1000)  # 51,152 micro-USD reserved.
    second = new_state(world.path, state['config'], bridge.tools)
    store.create('second-agent', second)
    with pytest.raises(LimitReached, match='budget reservation'):
        store.reserve('second-agent', second, 1000)
    with pytest.raises(LimitReached, match='attempt allowance'):
        store.create('third-agent', new_state(world.path, state['config'], bridge.tools))


def test_shared_clock_idempotency_rejects_different_retry_arguments(tmp_path):
    world, _, _, _ = setup(tmp_path)
    first = world.advance(10, request_id='durable-clock')
    assert LabWorld(world.path).advance(10, request_id='durable-clock') == first
    with pytest.raises(WorldError, match='different arguments'):
        world.advance(20, request_id='durable-clock')
    assert world.inspect()['clock'].endswith('09:10:00-04:00')


def test_real_mcp_bridge_roundtrip_without_model_or_evaluator_access(tmp_path):
    world = LabWorld.reset('C01', 'bridge', runs_root=tmp_path)

    async def exercise():
        async with connect_world(world.path) as bridge:
            assert {t['name'] for t in bridge.tools} == ALLOWED_TOOLS
            send = next(t for t in bridge.tools if t['name'] == 'send_message')
            assert set(send['parameters']['properties']['topic']['enum']) == {'review_request','clarification','reminder','status_request'}
            context = await bridge.call('get_world', {})
            assert context['ok'] and 'world' in context['result']
            assert 'events' not in context['result']['world']
            assert 'not final client sign-off' in context['result']['output_guide']['handoff_scope']
            advance = {'minutes': 10, 'request_id': 'mcp-clock'}
            first = await bridge.call('advance_clock', advance)
            assert await bridge.call('advance_clock', advance) == first
            assert not (await bridge.call('evaluate', {}))['ok']
    asyncio.run(exercise())
    assert world.inspect()['clock'].endswith('09:10:00-04:00')
