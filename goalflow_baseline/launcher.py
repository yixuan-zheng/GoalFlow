"""Future operator launch with OS-level exit observations; never a discovery sweep.

This command can make paid requests and requires separate user authorization.
R01V2 pauses when both requests are sent and feedback is pending, exits, waits for
OS termination, and resumes in a fresh process with the same ledger and state.
"""
import argparse
from pathlib import Path
import subprocess
import sys

from .evidence import CENTRAL, now, process_observation
from .freeze import verify_freeze
from goalflow_world.store import ROOT, SAFE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--case', required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--evidence-root', type=Path, default=CENTRAL)
    args = parser.parse_args()
    frozen = verify_freeze(args.freeze, central=args.evidence_root)
    if not SAFE.fullmatch(args.run) or args.case not in frozen['matrix']:
        parser.error('Invalid run ID or case outside frozen matrix')
    common = [sys.executable,'-m','goalflow_baseline','--evidence-root',str(args.evidence_root)]
    first = ['new','--scope','discovery','--freeze',str(args.freeze),'--case',args.case,'--run',args.run]
    if args.case=='R01V2':
        first += ['--pause-when-waiting']
    actions = [('new',first)]
    if args.case=='R01V2':
        actions.append(('resume',['resume','--run',args.run]))
    for action, command in actions:
        started = now()
        child = subprocess.Popen(common+command, cwd=ROOT)
        status = child.wait()
        process_observation(args.evidence_root,args.run,pid=child.pid,returncode=status,action=action,started_at=started)
        if status:
            raise SystemExit(status)


if __name__=='__main__':
    main()
