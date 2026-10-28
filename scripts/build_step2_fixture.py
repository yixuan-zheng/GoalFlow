"""Version the clean handoff case; never overwrite C01 or reserved fixtures."""
import json
from goalflow_world.models import World, Event
from goalflow_world.store import ROOT


def main():
    original = ROOT/'fixtures/development/C01'
    target = ROOT/'fixtures/development/C01V2'
    if target.exists():
        raise SystemExit('C01V2 already exists; refusing to overwrite a versioned fixture')
    world = json.loads((original/'world.json').read_text())
    world['case_id'] = 'C01V2'
    world['goal'] += ' Prepare a revision handoff under Ada’s standing delegation; this is not final design sign-off.'
    world['messages'].append({
        'id': 'ada-handoff-delegation', 'sender': 'ada', 'recipient': 'coordinator',
        'thread': world['project_id'], 'topic': 'delegation',
        'body': ('For this review cycle, I authorize compatible, within-scope recommendations from both '
                 'required reviewers to enter the implementation revision brief without a separate decision '
                 'from me. This is standing authority for the revision handoff, not final sign-off on a '
                 'finished design or website. Keep the mandatory form fields, consent, accessibility and '
                 'CTA constraints. Bring material reviewer disagreements to me and scope changes to Mira. '
                 'Do not wait for an additional approval if both required reviews are compatible.'),
        'authored_at': world['clock'], 'delivered_at': world['clock'], 'artifact_version': 1,
    })
    visible = World.model_validate(world).model_dump()
    events = [Event.model_validate(e).model_dump() for e in json.loads((original/'events.json').read_text())]
    target.mkdir()
    (target/'world.json').write_text(json.dumps(visible, indent=2, ensure_ascii=False)+'\n')
    (target/'events.json').write_text(json.dumps(events, indent=2, ensure_ascii=False)+'\n')
    (target/'goal.md').write_text('# C01V2 — versioned clean handoff\n\n'+world['goal']+'\n\n'
        'C01 remains unchanged. This version adds actual standing authority from Ada, '
        'without disclosing future feedback or changing the review responses.\n')
    print('Created C01V2; original and reserved fixtures unchanged.')


if __name__ == '__main__':
    main()
