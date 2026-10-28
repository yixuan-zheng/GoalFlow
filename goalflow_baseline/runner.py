"""A persistent Responses/tool loop, without domain-specific plans or evaluation access."""
import asyncio
import hashlib
import json
from pathlib import Path
import time

import anyio

from goalflow_world.store import ROOT
from .bridge import ALLOWED_TOOLS
from .state import LimitReached, digest, encode


def fingerprint(config, tools):
    files = [*Path(__file__).parent.glob('*.py'), Path(__file__).parent/'prompt.md',
             ROOT/'tools/world_server.py', * (ROOT/'goalflow_world').glob('*.py'),
             ROOT/'config/world-schema-v1.sql', ROOT/'config/workflow-schema.sql', ROOT/'uv.lock']
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return digest({'files': hashes, 'config': config, 'tools': tools})


def new_state(run_path, config, tools):
    prompt = (Path(__file__).parent/'prompt.md').read_text()
    return {'run_id': run_path.name, 'run_path': str(run_path.resolve()), 'config': config,
            'fingerprint': fingerprint(config, tools), 'tools': tools, 'prompt': prompt,
            'history': [], 'pending': [{'type': 'function_call', 'call_id': 'initial-visible-world',
                'name': 'get_world', 'arguments': '{}', 'bootstrap': True}],
            'phase': 'tools_pending', 'status': 'ready', 'stop_reason': None,
            'model_turns': 0, 'tool_calls': 0, 'input_tokens': 0, 'output_tokens': 0, 'active_seconds': 0.0}


class OpenAIProvider:
    def __init__(self, api_key):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, max_retries=0, timeout=45)

    async def create(self, payload, timeout):
        response = await asyncio.to_thread(self.client.with_options(timeout=timeout).responses.create, **payload)
        return response.model_dump(mode='json', exclude_none=True)


class Runner:
    def __init__(self, store, agent, bridge, provider, *, clock=time.monotonic):
        self.store, self.agent, self.bridge, self.provider, self.clock = store, agent, bridge, provider, clock

    def save(self, state, kind, details=None):
        self.store.save(self.agent, state, kind, details)

    def stop(self, state, reason, *, paused=False):
        state.update(status='paused' if paused else 'stopped', stop_reason=reason)
        self.save(state, 'paused' if paused else 'stopped', {'reason': reason})

    def reserve_time(self, state, maximum):
        remaining = state['config']['max_active_seconds'] - state['active_seconds']
        if remaining <= 0:
            raise LimitReached('Active-time ceiling reached')
        timeout = min(maximum, remaining)
        state['active_seconds'] += timeout  # If interrupted, charge the full uncertain operation timeout.
        return timeout, self.clock()

    def settle_time(self, state, reservation):
        timeout, started = reservation
        state['active_seconds'] += min(timeout, max(0, self.clock() - started)) - timeout

    async def tool(self, state):
        call = state['pending'][0]
        if state['tool_calls'] >= state['config']['max_tool_calls']:
            raise LimitReached('Tool-call ceiling reached')
        try:
            args = json.loads(call['arguments'])
            if not isinstance(args, dict):
                raise ValueError
        except (ValueError, TypeError):
            args = None
        if args is not None and call['name'] == 'advance_clock' and not args.get('request_id'):
            args['request_id'] = 'clock-' + hashlib.sha256(call['call_id'].encode()).hexdigest()[:24]
        if 'dispatch_arguments' in call:
            args = call['dispatch_arguments']
        call['dispatch_arguments'] = args
        reservation = self.reserve_time(state, 15)
        state['tool_calls'] += 1
        state['phase'] = 'tool_inflight'
        self.save(state, 'tool_started', {'call_id': call['call_id'], 'name': call['name'], 'arguments': args})
        try:
            if args is None:
                result = {'ok': False, 'error': 'Tool arguments must be a JSON object'}
            elif call['name'] not in ALLOWED_TOOLS:
                result = {'ok': False, 'error': 'Tool is not allowed'}
            else:
                with anyio.fail_after(reservation[0]):
                    result = await self.bridge.call(call['name'], args)
        except Exception:
            # The effect may have committed. Keep the pending call and stable arguments for resume.
            self.settle_time(state, reservation)
            self.stop(state, 'tool_transport_uncertain', paused=True)
            return
        self.settle_time(state, reservation)
        if call.get('bootstrap'):
            if not result.get('ok'):
                self.stop(state, 'initial_world_unavailable')
                return
            state['history'].append({'role': 'user', 'content': 'Initial visible world from get_world:\n' + encode(result['result'])})
        else:
            state['history'].append({'type': 'function_call_output', 'call_id': call['call_id'], 'output': encode(result)})
        state['pending'].pop(0)
        state['phase'] = 'tools_pending' if state['pending'] else 'awaiting_model'
        if call['name'] == 'report_outcome' and result.get('ok'):
            state.update(status='claim_recorded', stop_reason='agent_claim_' + result['result']['status'])
        self.save(state, 'tool_result', {'call_id': call['call_id'], 'name': call['name'], 'result': result})

    async def model(self, state):
        cfg = state['config']
        if state['model_turns'] >= cfg['max_model_turns']:
            raise LimitReached('Model-turn ceiling reached')
        if state['tool_calls'] >= cfg['max_tool_calls']:
            raise LimitReached('Tool-call ceiling reached')
        allowance = (f"\nHost allowance including this request: {cfg['max_model_turns'] - state['model_turns']} "
                     f"model turns and {cfg['max_tool_calls'] - state['tool_calls']} tool attempts remain. "
                     "Use successful tool results instead of redundant polling; leave room for publication, read-back and outcome reporting.")
        payload = {'model': cfg['model'], 'instructions': state['prompt'] + allowance, 'input': state['history'],
                   'tools': state['tools'], 'parallel_tool_calls': False, 'tool_choice': 'auto',
                   'store': False, 'max_output_tokens': cfg['max_output_tokens'],
                   'reasoning': {'effort': cfg['reasoning_effort']}, 'include': ['reasoning.encrypted_content']}
        # Conservatively bound text/schema tokenization by twice its UTF-8 bytes + format allowance.
        # Actual provider usage is recorded; cached-token discounts/incentives are never assumed.
        input_bound = len(encode(payload).encode('utf-8')) * 2 + 8192
        reservation = self.reserve_time(state, 45)
        try:
            self.store.reserve(self.agent, state, input_bound)
        except LimitReached:
            self.settle_time(state, reservation)
            raise
        try:
            response = await self.provider.create(payload, reservation[0])
        except Exception as exc:
            self.settle_time(state, reservation)
            state.update(status='stopped', stop_reason='model_request_uncertain')
            self.save(state, 'provider_error', {'error_type': type(exc).__name__,
                      'http_status': getattr(exc, 'status_code', None)})
            return  # Hold the reservation; do not retry an ambiguously billable request.
        self.settle_time(state, reservation)
        usage = response.get('usage') or {}
        if not isinstance(usage.get('input_tokens'), int) or not isinstance(usage.get('output_tokens'), int):
            self.stop(state, 'model_usage_missing')
            return
        self.store.response(self.agent, state, response.get('output', []), usage['input_tokens'], usage['output_tokens'],
                            {'model': response.get('model'), 'status': response.get('status'), 'response_id': response.get('id')})
        if state['status'] == 'running' and not state['pending']:
            self.stop(state, 'model_stopped_without_outcome_claim')

    async def run(self, *, pause_after_tools=None):
        state = self.store.load(self.agent)
        if fingerprint(state['config'], self.bridge.tools) != state['fingerprint']:
            raise ValueError('Code, prompt, settings or tool schemas changed; refusing to resume a different baseline')
        if state['phase'] == 'model_inflight':
            self.stop(state, 'model_request_uncertain_after_restart')
            return self.store.summary(self.agent)
        if state['status'] in ['stopped', 'claim_recorded']:
            return self.store.summary(self.agent)
        starting_calls = state['tool_calls']
        state.update(status='running', stop_reason=None)
        self.save(state, 'resumed', {'tool_calls': starting_calls})
        while state['status'] == 'running':
            if pause_after_tools is not None and state['tool_calls'] - starting_calls >= pause_after_tools:
                self.stop(state, 'requested_checkpoint_pause', paused=True)
                break
            try:
                if state['pending']:
                    await self.tool(state)
                else:
                    await self.model(state)
            except LimitReached as exc:
                self.stop(state, str(exc))
        return self.store.summary(self.agent)
