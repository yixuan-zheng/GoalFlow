import argparse
import json
from pathlib import Path
from .store import LabWorld, WorldError, ROOT

def main():
    p=argparse.ArgumentParser(description='GoalFlow offline development world; no API calls')
    p.add_argument('--runs-root', type=Path, default=ROOT/'runs')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('list')
    r=sub.add_parser('reset');r.add_argument('case');r.add_argument('--run',required=True);r.add_argument('--replace',action='store_true')
    r.add_argument('--fixture-group', choices=['development', 'validation'], default='development')
    for name in ['inspect','timeline','context']:
        s=sub.add_parser(name);s.add_argument('--run',required=True)
    a=sub.add_parser('advance');a.add_argument('--run',required=True);a.add_argument('--minutes',type=int,required=True)
    s=sub.add_parser('send');s.add_argument('--run',required=True);s.add_argument('--to',required=True);s.add_argument('--topic',required=True)
    s.add_argument('--body',required=True);s.add_argument('--request-id',required=True);s.add_argument('--version',type=int);s.add_argument('--subject')
    d=sub.add_parser('decision');d.add_argument('--run',required=True);d.add_argument('--message',required=True)
    b=sub.add_parser('read-brief');b.add_argument('--run',required=True);b.add_argument('--brief-id',required=True);b.add_argument('--revision',type=int,required=True)
    args=p.parse_args()
    try:
        if args.command=='list':
            result=[{'case_id':d.name,'goal':json.loads((d/'world.json').read_text())['goal']} for d in sorted((ROOT/'fixtures/development').iterdir()) if (d/'world.json').exists()]
        elif args.command=='reset':
            w=LabWorld.reset(args.case,args.run,replace=args.replace,runs_root=args.runs_root,fixture_group=args.fixture_group)
            result={'run':args.run,'case':args.case,'mode':'offline-synthetic','clock':w.inspect()['clock']}
        else:
            from .store import SAFE
            if not SAFE.fullmatch(args.run):raise WorldError('Invalid run ID')
            w=LabWorld(args.runs_root/args.run)
            if args.command=='inspect':result=w.inspect()
            elif args.command=='timeline':result=w.timeline()
            elif args.command=='context':result=w.workflow_context()
            elif args.command=='read-brief':result=w.read_brief(args.brief_id,args.revision)
            elif args.command=='advance':result=w.advance(args.minutes)
            elif args.command=='send':result=w.send_message(args.to,args.topic,args.body,args.request_id,args.version,args.subject)
            else:result=w.record_decision(args.message)
        print(json.dumps(result,indent=2,ensure_ascii=False))
    except (WorldError,FileNotFoundError) as e:
        p.exit(2,f'World error: {e}\n')

if __name__=='__main__':main()
