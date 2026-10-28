// Application-to-upstream assessment adapter. Upstream files are never modified.
import { readFileSync } from 'node:fs';
import { arbitrateNativeStatus } from './vendor/status-arbiter.ts';

const request = JSON.parse(readFileSync(0, 'utf8'));
const hasEvidence = !!request.evidence && (typeof request.evidence !== 'object' || Object.keys(request.evidence).length > 0);
const verified = request.kind === 'complete' && request.authorized === true && hasEvidence;
const assessment = {
  reportedDisposition: request.kind === 'complete' ? 'done' : request.kind === 'block' ? 'blocked' : 'yielded',
  objectiveSatisfied: verified,
  allCriteriaSatisfied: verified,
  verificationPassed: verified,
  hasFailedVerification: request.kind === 'complete' && !verified,
  hasBlockingRemainingWork: !verified,
  attentionRequests: [],
  summary: request.reason,
  criterionAssessments: [],
  continuation: request.kind === 'continue' ? {
    kind: 'same_agent', summary: request.reason, idempotencyKey: `attempt:${request.attempt_id}`,
  } : null,
  blocker: request.kind === 'block' ? {
    scope: 'task_wide', boardOwned: true, unblockAction: request.reason,
  } : null,
};
const decision = arbitrateNativeStatus({
  assessment, terminalState: 'succeeded', workspaceFinalizeStatus: 'succeeded',
  priorIssueStatus: 'in_progress', agentId: request.attempt_id,
  allowIncompleteContinuation: false,
  // Custom local event delivery materializes this execution-stage gate. It is
  // not an upstream Paperclip interaction service or native scheduler.
  governanceGate: request.kind === 'wait' ? { kind: 'execution_stage', id: request.wait_key } : null,
});
process.stdout.write(JSON.stringify(decision));
