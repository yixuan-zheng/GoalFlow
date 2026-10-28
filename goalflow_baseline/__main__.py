"""Operator CLI for bounded Step 2 smoke attempts. No discovery sweep command."""
import argparse
import asyncio
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path

from goalflow_world.store import LabWorld, ROOT, SAFE
from .bridge import connect_world
from .runner import OpenAIProvider, Runner, new_state
from .state import StateStore, digest
from .evidence import CENTRAL, EvidenceSession, ObservedStore, WaitingBoundary
from .freeze import verify_freeze


@contextmanager
def lock_run(path):
    folder = path/'baseline'
    folder.mkdir(exist_ok=True)
    with (folder/'runner.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another baseline process owns this run') from None
        yield


async def execute(args, store, run_path, agent):
    with lock_run(run_path):
        async with connect_world(run_path) as bridge:
            if args.command == 'new':
                config = json.loads((ROOT/'config'/('discovery.json' if args.scope=='discovery' else 'baseline.json')).read_text())
                if args.scope == 'discovery':
                    verify_freeze(args.freeze, tools=bridge.tools, central=args.evidence_root)
                state = new_state(run_path, config, bridge.tools)
                state['case_id'] = args.case
                state['discovery_freeze'] = str(args.freeze.resolve()) if args.freeze else None
                store.create(agent, state)
            else:
                state = store.load(agent)
                if state['config'].get('scope') == 'discovery':
                    verify_freeze(Path(state['discovery_freeze']), tools=bridge.tools, central=args.evidence_root)
            session = EvidenceSession(store, agent, central=args.evidence_root, action=args.command,
                                      pause_when_waiting=args.pause_when_waiting)
            observed = ObservedStore(store, session)
            # Load credentials only here; never pass .env or keys to tools, checkpoints or logs.
            try:
                from dotenv import dotenv_values
                values = dotenv_values(ROOT/'.env')
                if values.get('GOALFLOW_MODEL') != state['config']['model']:
                    raise ValueError('Configured model differs from frozen baseline model')
                key = values.get('OPENAI_API_KEY')
                if not key:
                    raise ValueError('Local API key is missing')
                provider = OpenAIProvider(key)
                try:
                    result = await Runner(observed, agent, bridge, provider, clock=session.operation_clock).run(pause_after_tools=args.pause_after_tools)
                except WaitingBoundary:
                    result = store.summary(agent)
                store.export(agent)
            except BaseException as exc:
                session.finish('exception', type(exc).__name__)
                raise
            else:
                session.finish('returned')
                return result


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs-root', type=Path, default=ROOT/'runs')
    parser.add_argument('--ledger', type=Path, default=ROOT/'data/baseline.sqlite')
    parser.add_argument('--evidence-root', type=Path, default=CENTRAL)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ['new', 'resume', 'inspect', 'export']:
        item = sub.add_parser(command)
        item.add_argument('--run', required=True)
        if command in ['new', 'resume']:
            item.add_argument('--pause-after-tools', type=int)
            item.add_argument('--pause-when-waiting', action='store_true')
        if command == 'new':
            item.add_argument('--scope', choices=['step2','discovery'], default='step2')
            item.add_argument('--freeze', type=Path)
            item.add_argument('--case', choices=['C01', 'C01V2', 'C04', 'C06', 'C05DEV', 'C07DEV', 'R01',
                                               'C04V2','C06V2','C05DEVV2','C07DEVV2','R01V2'], default='C01V2')
    args = parser.parse_args()
    if args.command=='new' and args.scope=='discovery':
        if not args.freeze:
            parser.error('Discovery requires an exact prepared --freeze directory')
        verify_freeze(args.freeze, central=args.evidence_root)
    if not SAFE.fullmatch(args.run):
        parser.error('Invalid run ID')
    if getattr(args, 'pause_after_tools', None) is not None and args.pause_after_tools < 1:
        parser.error('Pause count must be positive')
    run_path = (args.runs_root/args.run).resolve()
    if run_path.parent != args.runs_root.resolve():
        parser.error('Run must be directly inside the configured runs root')
    agent = digest(str(run_path))[:24]
    store = StateStore(args.ledger)
    try:
        if args.command == 'inspect':
            result = store.summary(agent)
        elif args.command == 'export':
            result = {'exported': str(store.export(agent))}
        else:
            if args.command == 'new':
                LabWorld.reset(args.case, args.run, runs_root=args.runs_root)
            result = asyncio.run(execute(args, store, run_path, agent))
        print(json.dumps(result, indent=2))
    except (ValueError, FileNotFoundError) as exc:
        # These are controlled local validation messages, not provider exception bodies.
        parser.exit(2, f'Baseline error: {exc}\n')
    except Exception as exc:
        parser.exit(2, f'Baseline stopped with {type(exc).__name__}; raw error details suppressed\n')


if __name__ == '__main__':
    main()
