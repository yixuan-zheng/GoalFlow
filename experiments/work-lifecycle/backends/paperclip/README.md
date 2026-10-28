# Paperclip status-arbiter extraction

This experimental baseline executes Paperclip's **unmodified** pure status arbiter at commit
`4dfcb4c9b8043d7fadaaed5f6cbab0c1e5cf8f2f` (`phase6-v11`). It is not a deployment of Paperclip.

## Why an extraction

The pinned root `package.json` requires Node >=24.11.0, while this machine has Node 22.23.3.
The native server depends on embedded PostgreSQL, many workspace packages, runner builds,
and agent/provider adapters. The full `status-decision-committer.ts` imports database schemas,
issue services, governance checks, delivery queues, native results, and platform publications.
Installing and configuring that application is outside this small extraction's setup budget.
No native server installation was attempted; its installation effort was not measured.

The arbiter itself has only one runtime import, `native-provider-failure.ts`; its other
imports are TypeScript types erased at execution. Both files are copied byte-for-byte,
with their MIT license and pinned provenance. Node's built-in type stripping executes them.
`resolve-ts.mjs` maps the original `.js` relative import to the corresponding `.ts` file,
so upstream files do not need source edits or a TypeScript compiler dependency.

## Boundaries and comparison limits

- Upstream code decides accepted disposition from application-supplied evidence assessments.
- SQLite storage, attempt ownership, revision fencing, event correlation and deduplication,
  transactional continuation intent, and test transport are **custom experiment code**.
- The upstream PostgreSQL committer, runner, recovery scheduler, auth system, UI, evidence
  classifier and governance integrations are not executed here.
- This baseline measures whether the pure decision boundary is conveniently extractable.
  It cannot measure Paperclip product setup, total product correctness, or production reliability.
- Count all custom adapter/persistence/transport code and configuration in comparisons.
  Report vendored upstream source separately, without pretending it was authored for this experiment.

## Pinned primary sources

- [Status arbiter](https://github.com/paperclipai/paperclip/blob/4dfcb4c9b8043d7fadaaed5f6cbab0c1e5cf8f2f/server/src/services/native-runtime/status-arbiter.ts)
- [Decision committer](https://github.com/paperclipai/paperclip/blob/4dfcb4c9b8043d7fadaaed5f6cbab0c1e5cf8f2f/server/src/services/native-runtime/status-decision-committer.ts)
- [Root package manifest](https://github.com/paperclipai/paperclip/blob/4dfcb4c9b8043d7fadaaed5f6cbab0c1e5cf8f2f/package.json)
- [Server package manifest](https://github.com/paperclipai/paperclip/blob/4dfcb4c9b8043d7fadaaed5f6cbab0c1e5cf8f2f/server/package.json)

## Source verification

`provenance.json` records Git blob identities and source URLs. SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `vendor/status-arbiter.ts` | `a62a9852fb036dad146a4051bd3e0f18c8e8ce3968d87317c2842687e9609cc6` |
| `vendor/native-provider-failure.ts` | `1a3a6da4a50738fbd49981db835cad1d91c43ed007d15fac55836549493c736f` |
| `vendor/LICENSE` | `7f8a27f0979bded50e240caa8c8c29f3088ddf87032cb83e5a9732bff91d18b4` |
