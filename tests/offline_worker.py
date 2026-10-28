"""Explicit subprocess test fixture. No SDK provider, credentials or real requests."""
import argparse
import asyncio
import json
import os
from pathlib import Path

from goalflow_baseline.bridge import connect_world
from goalflow_baseline.evidence import EvidenceSession, ObservedStore, WaitingBoundary
from goalflow_baseline.runner import Runner, new_state
from goalflow_baseline.state import StateStore, digest
from goalflow_world.store import LabWorld, ROOT
from scripts.step1_reference import REQUIREMENTS


def actions():
    refs=['message:in-leo-review','message:in-nia-review','message:ada-handoff-delegation']
    items=[]
    tasks=[]
    for key,value,text,source in [
        ('form_layout','compact_single_step','Use a compact single-step form with name/email and unchecked consent.',refs),
        ('hero_copy','Evening learning, at your pace.','Set headline to Evening learning, at your pace.',['message:in-leo-review']),
        ('contrast','improve_heading_contrast','Check workshop-card heading text contrast and correct it.',['document:brief@1','message:in-nia-review']),
        ('keyboard','preserve_keyboard_focus','Verify visible focus and keyboard order through the form and CTA.',['document:brief@1','message:in-nia-review'])]:
        ident='task-'+key
        tasks.append({'id':ident,'owner':'tomas','title':text,'status':'todo','acceptance':text,
                      'source_ids':source,'artifact_version':1,'change_key':key,'change_value':value})
        items.append({'key':key,'value':value,'instruction':text,'source_ids':source,'task_ids':[ident], 'disposition':'accepted'})
    sequence=[('send_message',{'recipient':p,'topic':'review_request','body':'Please review this revision.','request_id':'ask-'+p}) for p in ['leo','nia']]
    sequence += [('advance_clock',{'minutes':20})]
    sequence += [('update_task',{'task':t,'request_id':'write-'+t['id']}) for t in tasks]
    # Existing skeletal application tasks need real coverage or explicit retirement.
    for ident in ['implement-form','verify-contrast']:
        sequence.append(('update_task',{'task':{'id':ident,'owner':'tomas','title':'Replaced by specific handoff task',
            'status':'cancelled','acceptance':'Replaced by the evidence-linked task set.','source_ids':['document:brief@1']},'request_id':'retire-'+ident}))
    sequence.append(('update_task',{'task':{'id':'review-home','owner':'mira','title':'Collect Home design review',
        'status':'done','acceptance':'Both required reviews are collected under standing delegation.',
        'source_ids':refs,'artifact_version':1},'request_id':'close-review'}))
    brief={'title':'Offline reference handoff','artifact_id':'design','artifact_version':1,'status':'ready',
        'summary':'Revision handoff under standing authority; implementation and final client design sign-off remain pending.',
        'requirements':REQUIREMENTS,'reviews':[{'reviewer':p,'source_ids':['message:in-'+p+'-review']} for p in ['leo','nia']],
        'decision_source_ids':['message:ada-handoff-delegation'],'items':items,'blockers':[]}
    sequence += [('publish_brief',{'brief_id':'handoff','brief':brief,'request_id':'publish'}),
                 ('read_brief',{'brief_id':'handoff','revision':1}),
                 ('report_outcome',{'status':'completed','brief_id':'handoff','revision':1,'request_id':'report'})]
    return sequence


async def execute(args):
    store=StateStore(args.root/'ledger.sqlite')
    path=args.root/'worlds'/args.run_id
    agent=digest(str(path.resolve()))[:24]
    if args.action=='new':
        LabWorld.reset('R01V2',path.name,runs_root=path.parent)
    async with connect_world(path) as bridge:
        if args.action=='new':
            config=json.loads((ROOT/'config/discovery.json').read_text())
            state=new_state(path,config,bridge.tools)
            state['case_id']='R01V2'
            store.create(agent,state)
        class Provider:
            async def create(self,payload,timeout):
                index=store.load(agent)['model_turns']-1
                seq=actions() if args.mode=='waiting' else [('advance_clock',{'minutes':10})]
                output=[]
                if index<len(seq):
                    name,arguments=seq[index]
                    output=[{'type':'function_call','name':name,'arguments':json.dumps(arguments),'call_id':'offline-'+str(index)}]
                return {'id':'offline-response-'+str(index),'model':'synthetic-no-network','status':'completed',
                        'usage':{'input_tokens':20,'output_tokens':10},'output':output}
        if args.mode=='crash' and args.action=='new':
            original=bridge.call
            async def crash_call(name,arguments):
                result=await original(name,arguments)
                if name=='advance_clock':
                    os._exit(73)  # Actual process loss after commit, before host acknowledgment.
                return result
            bridge.call=crash_call
        session=EvidenceSession(store,agent,central=args.central,action=args.action,
                                pause_when_waiting=args.mode=='waiting' and args.action=='new')
        observed=ObservedStore(store,session)
        try:
            try:
                result=await Runner(observed,agent,bridge,Provider(),clock=session.operation_clock).run()
            except WaitingBoundary:
                result=store.summary(agent)
            store.export(agent)
        finally:
            session.finish('offline_worker_returned')
        print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['new','resume'])
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--central',type=Path,required=True)
    parser.add_argument('--mode',choices=['waiting','crash'],default='waiting')
    parser.add_argument('--run-id',default='offline-restart')
    asyncio.run(execute(parser.parse_args()))
