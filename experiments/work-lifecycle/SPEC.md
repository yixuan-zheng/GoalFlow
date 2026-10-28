# Work lifecycle portability experiment — frozen contract v1

Frozen before lifecycle implementation on 2026-10-22. This experiment is separate from the preserved Cedar Studio study. Changes to this contract require an entry in `DECISIONS.md`; never silently change expected outcomes after seeing results.

## Question and decision rule

Can persistent work, finite attempts and accepted dispositions reduce application lifecycle engineering across a coding assignment and a research assignment?

All backends must pass the same observable contract. Correctness alone is not an advantage. A candidate merits a further independent application trial only if (a) every required scenario passes; (b) its core transfers unchanged from coding to research; (c) the complete custom integration, lifecycle, configuration and adapter burden is materially smaller than the strongest competent comparator; (d) policy control and diagnosis remain available; (e) there is one authoritative lifecycle store. For this exploratory engineering exercise, material reduction means at least 30% fewer nonblank, noncomment custom lines across the full solution, supported by an explanation of mechanisms removed, not mere syntax compression. Report component development separately from per-application integration, include hidden adapters, and do not treat lines or agent wall time as measured human productivity.

If the reduction is absent, core changes are needed for the second domain, only a weak extraction is beaten, or extra sources of truth are introduced, do not recommend a general framework. A small library remains a hypothesis. Do not optimize implementations for line count or retrofit the threshold.

## Implementations

1. A real locally running Restate virtual object, with native serialized state and durable journal. It owns lifecycle state; the Python client has no shadow store.
2. Exact pinned Paperclip status-arbiter and its runtime dependency, executed in Node, with a custom persistence/lifecycle adapter. Full Paperclip requires a larger installation and newer Node than the available v22. This extraction tests policy reuse and **cannot establish superiority over the full Paperclip product**. Count all custom glue and report retained upstream code separately.
3. A minimal Python/SQLite GoalFlow component. It must be implemented after baseline designs are available; do not import or copy baseline transition code. Domain policies and workers remain external.

The common harness supplies artifacts, policy decisions, a deterministic event schedule, an external scheduler and assertions. It supplies no lifecycle transition implementation. Backends may implement the protocol idiomatically and use different internal representations.

## Applications and policy boundary

Coding: implement a small Python function against a versioned specification; a first implementation fails local tests, a later attempt repairs it; wait for CI/review between attempts. Research: run analysis over a fixed local dataset, persist a partial result, wait for a background result, then produce a verifiable report. Version 2 changes the coding requirement or research scope after an artifact already exists.

Actual files, subprocess execution of coding tests and deterministic checking of research calculations provide evidence. Scripted workers are intentional. The application computes `authorized` for completion from its verifier and an allowed reviewer identity; worker claims do not control it. Backends treat the caller as a trusted application boundary. These are not authenticated public APIs. Domain policies, which results are obsolete, retry limits and scheduler delivery are not inferred by the core.

## Observable JSON protocol

Each backend exports `Backend(root: pathlib.Path)` with `command(request: dict) -> dict` and optional `close()`. Each scenario gets a fresh root; all work is keyed by `work_id`. The harness will execute commands in fresh processes, so state cannot live only in client memory. Request `now` is a deterministic integer clock used for leases, never wall-clock performance.

Response: `{ok: bool, code: str, state: snapshot|null}`. A snapshot contains at least `work_id`, `domain`, `revision`, `status`, `active_attempt` (ID or null), `wait_key` (string or null), `attempts` (list), `events` (list), `wakes` (list), and `history` (list). Additional diagnostic fields are welcome. Allowed statuses: ready, running, waiting, blocked, completed, cancelled. Attempt records contain id, revision, status, lease_until. Events contain id, key, revision, attempt_id, status, payload. Wakes contain id, revision, cause, status (pending/delivered). IDs and ordering are backend-defined except caller-supplied attempt/event IDs. History must make accepted transitions and rejections understandable; audit order/format is not asserted.

| Operation | Request and expected semantics |
| --- | --- |
| create | work_id, domain, revision=1. New work is ready with no attempts. Duplicate create returns existing state; conflicting domain/revision rejects. |
| inspect | Return durable snapshot; absent work yields not_found. |
| start | attempt_id, revision, now, lease_seconds=5. Only ready work can acquire an attempt. Revision must be current. A previously used attempt ID never creates another attempt. One active owner. Successful start sets running and active_attempt. |
| finish | attempt_id, revision, kind (complete/continue/wait/block), reason; wait also has wait_key; complete also has authorized and evidence. Only the active running attempt at the current revision may finish. Repeating the identical finish is harmless; changing a finished attempt's disposition rejects. Complete without authorized=true rejects and leaves the active attempt running. Accepted complete sets completed; continue sets ready and records a pending wake; block sets blocked; wait sets waiting unless a matching buffered event already exists, in which case consume it, set ready and record one wake. Accepted finish clears ownership. |
| event | event_id, key, revision, attempt_id, payload. Same ID/payload is a harmless replay; same ID with different contents rejects. Correlate to an existing attempt of that revision. Future revisions/unknown attempts reject. Obsolete revision records stale; cancelled/completed/blocked work records ignored. Current active-attempt events may buffer before finish(wait). Matching waiting key and its waiting attempt consumes one event, sets ready and records one wake. Nonmatching events buffer but cannot complete work. A result from a superseded attempt is stale even at the same revision. |
| revise | revision=current+1, reason. Increment specification after partial work. Cancelled/completed work rejects. Supersede active or waiting attempt, clear wait and ownership, mark old buffered events stale, set ready, add one pending wake. Same target revision is idempotent. Prior pending wakes become obsolete/delivered (not runnable). |
| cancel | reason. Cancel non-completed work, invalidate active attempt, clear wait and pending wakes (mark delivered with diagnostic reason). Repeated cancellation is harmless. Completed work is unchanged/rejected. |
| recover | now. Expired active lease becomes abandoned, ownership clears, ready plus one pending wake. Nonexpired owner is left alone. Repeated recovery without a new expired owner produces no extra wake. Does not execute work. |
| ack | wake_id. Mark the corresponding durable intent delivered; duplicate ack is harmless. Delivery/start is external. |

Invalid operations, malformed requests and stale ownership must not partially mutate work. Wake intent and the transition requiring continuation must commit together. A result is evidence for the application, not itself authority to complete an assignment. Only one matching event is consumed for a wait. The shared scheduler starts an attempt with a deterministic ID derived from the wake, then acknowledges; duplicate delivery therefore cannot start another attempt even if the acknowledgement was lost.

## Fixed scenarios (each in both domains, for all three backends)

1. **normal_continuation**: write invalid artifact, finish wait, deliver feedback, start later attempt, repair artifact and complete after verification.
2. **early_event**: result arrives while attempt is running; subsequent wait observes it and resumes.
3. **duplicate_event**: identical event delivered repeatedly, including after consumption; one event and one wake only; conflicting replay rejected.
4. **revision_after_artifact**: write v1 artifact, revise while attempt is active, reject stale completion/event, run v2 and verify repaired artifact. Prove artifact existed before revision.
5. **cancel_late_result**: cancel waiting work, deliver result and retry start; work remains cancelled.
6. **unsupported_completion**: invalid artifact or unauthorized reviewer cannot complete; valid authorized artifact can complete.
7. **worker_crash**: kill client worker after a durable start; recover only after lease expiry, start replacement, reject old worker finish, complete.
8. **missed_wake**: kill client immediately after committing continue and before delivering wake; fresh process reads durable intent, scheduler starts and acknowledges, complete.
9. **duplicate_wake**: scheduler start succeeds but ack is lost; repeat deterministic start, then ack; exactly one attempt for that wake.
10. **stale_same_revision**: old attempt's delayed result cannot wake a later wait for the same key at the same specification revision.
11. **bounded_no_progress**: application permits three attempts, then accepts block; duplicate/late events cannot restart blocked work. Limit is application policy.
12. **restart_persistence**: create/wait/event in fresh client processes, restart the actual backing service where applicable, then resume and complete; no volatile client state is required.

Additional invariant/race/invalid-input tests may be added, labeled supplemental and not substituted for these twelve. Check negative outcomes before repairing any fixture; final completion alone is insufficient. Distinguish client kill, service restart, and storage-transaction fault injection in reporting. No claim of arbitrary external-effect exactly-once delivery, power-loss resilience, semantic dependency discovery or LLM intelligence.

## Execution and evidence

Run the 12 x 2 x 3 = 72 deterministic scenario cells, retaining commands, responses, assertion outcomes, artifacts, backend versions, logs and raw JSON results. A pass requires every assertion, not simply a final status. Repeat only to validate fixes, retaining prior failures and change history. Record first coding completion/core hash before research transfer; compare core hash afterward. Report corrections required by supplemental review separately.

Measure custom source/config/adapter lines with an explicit file manifest; report shared harness/policy/fixtures and retained vendor code separately. Record setup steps and observed development fixes without invented human-hour estimates. Native dependencies' source lines are not charged to the app; new GoalFlow component source is reported as both development investment and reusable component, never hidden. Results should enable a decision to stop, contribute an example, or test a small library further.
