"""Operator discovery freeze; source validation never invokes a provider."""
import json
from pathlib import Path

from .bridge import ALLOWED_TOOLS
from .evidence import CENTRAL, EvidenceError, encode, sha, source_snapshot, source_files, verify_tree, versions, write_new, seal
from goalflow_world.store import ROOT


def create_freeze(tools, *, central=CENTRAL, budget=None, validation=None):
    central = Path(central)
    source_id = source_snapshot(central)
    source = central/'project/frozen-sources'/source_id
    config = json.loads((ROOT/'config/discovery.json').read_text())
    source_manifest = verify_tree(source)
    manifest = {'kind':'discovery-freeze-v1', 'source_snapshot':source_id,
        'source_files':source_manifest['files'], 'tools':tools, 'settings':config,
        'dependencies':versions(), 'permissions':{'tools':sorted(ALLOWED_TOOLS),
            'local_synthetic_messages_only':True, 'external_system_writes':False,
            'agent_filesystem_or_evaluator_access':False,
            'boundary':'Application capability boundary, not an OS sandbox'},
        'budget_at_freeze':budget, 'offline_validation':validation,
        'execution_authorized':False, 'matrix':config['case_attempts']}
    identity = sha(encode(manifest))
    folder = central/'project/discovery-freezes'/identity
    folder.mkdir(parents=True, exist_ok=False)
    write_new(folder/'freeze.json', encode(manifest))
    seal(folder, {'kind':'immutable-discovery-freeze', 'freeze_id':identity})
    verify_freeze(folder, tools=tools, central=central)
    return folder


def verify_freeze(folder, *, tools=None, central=CENTRAL):
    folder = Path(folder)
    verify_tree(folder)
    raw = (folder/'freeze.json').read_bytes()
    if sha(raw) != folder.name:
        raise EvidenceError('Discovery freeze identity mismatch')
    frozen = json.loads(raw)
    if {str(p.relative_to(ROOT)) for p in source_files()} != set(frozen['source_files']):
        raise EvidenceError('Source inventory differs from discovery freeze')
    verify_tree(Path(central)/'project/frozen-sources'/frozen['source_snapshot'])
    for name, expected in frozen['source_files'].items():
        if sha((ROOT/name).read_bytes()) != expected:
            raise EvidenceError('Current source differs from discovery freeze')
    if versions() != frozen['dependencies']:
        raise EvidenceError('Installed runtime dependencies differ from freeze')
    if tools is not None and tools != frozen['tools']:
        raise EvidenceError('MCP schemas differ from discovery freeze')
    return frozen
