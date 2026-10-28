# GoalFlow publication verification — October 28, 2026

**Verdict: GO.** The owner authorized public publication under `yixuan-zheng/GoalFlow`. The approved source was published with fresh Git history and actual GitHub Actions validation passed. No new agent feature, paid model study or historical rescore was introduced.

## Public repository and inventory

- Repository: [yixuan-zheng/GoalFlow](https://github.com/yixuan-zheng/GoalFlow), public access confirmed by an unauthenticated API request and clone.
- Initial publication commit: `7f4c8a5a2681c06e42fd65599641124b8e361b94`.
- Initial tree: all 209 approved candidate files matched byte-for-byte.
- Publication-only follow-up: `README.md`, `docs/VALIDATION.md`, this report and `FILE_INVENTORY.json`. These record actual publication/CI, add the status badge and refresh inventory hashes. No files added or removed; all other 205 files remain unchanged.
- `FILE_INVENTORY.json` lists all other files, sizes and SHA-256, intentionally excluding its own recursive hash. The source approval and historical findings remain intact.

## Actual GitHub validation

The initial commit's [hosted Actions run](https://github.com/yixuan-zheng/GoalFlow/actions/runs/40780679105) concluded **success**. Both Linux Python 3.12 and 3.13 jobs ran locked dependency installation, **93 baseline tests**, **38/38 lifecycle cells**, the credential-free subprocess MCP/revision demo and the historical evidence verifier. Logs show pending semantic review rather than an invented human pass, and verify seven historical records plus exact upstream Paperclip Git blobs. No historical experiment was rerun.

The publication-only follow-up triggers the same workflow; [latest results](https://github.com/yixuan-zheng/GoalFlow/actions/workflows/offline.yml) identify its commit and conclusion. The final user-facing publication report supplies the final SHA and matching run URL without creating a self-referential commit hash in this document. See `docs/VALIDATION.md` for prior clean macOS/local Linux validation and initial hosted timings.

## Licensing, privacy and provenance

Ownership and MIT licensing were explicitly confirmed by the owner. The root MIT license and original Paperclip copyright/license remain unchanged. The exact upstream Git blobs verify; `THIRD_PARTY_NOTICES.md`, dependency notices and source provenance remain included. Dependencies retain their own licenses; external SDKs/runtimes are not bundled or relicensed.

A whole-tree publication audit found no credential signatures, private machine paths, unexpected private emails, SQLite/runtime databases, hidden ledgers, symlinks, archives, caches or unrelated histories. The 137 synthetic `.test` address occurrences and 14 public upstream attribution emails are intentional. No raw databases/logs/archives are distributed. Markdown local targets resolve and the public README exposes its Mermaid architecture. Signature scans cannot guarantee absence of every possible secret; the full internal archives remain private.

Original development directories and the approved release candidate were preserved. Publication uses a separate clean working copy. Historical records are unchanged full copies or clearly labeled exact-line excerpts, with hashes and omitted private material documented in the evidence index.

## Repository metadata

Description: A durable agent-workflow evaluation lab with a persistent MCP baseline, synthetic workflows, and inspectable lifecycle evidence.

Topics: `ai-agents`, `mcp`, `agent-evaluation`, `workflow-engine`, `python`, `sqlite`.

## Remaining limitations

Human semantic review of the hosted-model study remains unresolved. Step 3 is still ten automatic passes and two rejected claims; separate AI adjudication found one material omission without a recurring mechanism. The historical lifecycle comparison remains 112/112 cells with 8.8% source reduction against a 30% gate. Integrity verification does not reproduce every historical assertion.

Optional hosted-model, Google and Restate/Paperclip execution were not revalidated for publication. Production reliability, remote exactly-once effects, generalization, developer-productivity improvement and novelty as an orchestration framework remain unsupported claims. CI emitted nonblocking action-runtime and runner-image transition notices; no test failed and no assertion was weakened.

Publication and verification complete the requested project scope. Further work is limited to an actual release defect.
