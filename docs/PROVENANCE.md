# Provenance and license review

The release derives from the approved standalone Phase 1 copy. Original development folders, credentials, raw studies, ledgers and archives were preserved. `SOURCE_PROVENANCE.json` retains original source hashes and lists Phase 1 portability changes; the release inventory hashes the final candidate separately.

The owner explicitly confirmed permission to publish independently authored code, fixtures and reports under MIT during this release review. `LICENSE` applies to that work. This confirmation is owner attestation, not an independent audit of employment or contractual obligations.

Independently authored: synthetic world and fixtures, agent loop/checkpoints/accounting, MCP adapter/server, evaluator/capture/freeze code, WorkStore, application verifiers, common test harness and custom backend adapters. The code was developed with AI assistance; no independent human validation or productivity measurement is implied.

Vendored upstream: two unchanged Paperclip TypeScript files and its MIT license. Their original commit, Git blob hashes and source URLs remain in the adjacent provenance file. The verifier checks these exact blobs. The extraction does not implement or benchmark the full Paperclip product.

External dependencies are installed, not bundled. The dependency inventory records installed distribution license declarations, and includes their supplied notices separately. certifi remains MPL-2.0; it is not relicensed as MIT. Restate SDK/server, OpenAI and Google SDKs are optional external dependencies and are not distributed in this candidate. Their own terms govern optional installation/use. No compatibility conflict was identified in the shipped vendored MIT code; this does not transfer ownership of dependencies or certify unseen obligations.

Historical evidence is copied unchanged or excerpted by exact line ranges, with hashes and explicit omissions. Complete machine-specific traces, SQLite stores, archives and runtime internals were excluded rather than edited. Synthetic `.test` identities and public upstream contributor copyright notices are intentional, not private customer data.
