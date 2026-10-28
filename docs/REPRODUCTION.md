# Reproduction

Use the README commands in a clean source checkout with Python 3.12 or 3.13. `requirements-offline.lock` pins direct and transitive core/test dependencies. An initial install downloads packages; execution then needs no network or credentials. On macOS with a certificate-store error, use the trusted system CA bundle via `pip --cert /etc/ssl/cert.pem`; never disable TLS verification.

`uv.lock` remains original study metadata used by historical fingerprint/version code, not the current installation lock. Core tests use a scripted provider and real local stdio MCP subprocesses. No hosted-model or Google SDK is needed. Each lifecycle command uses a new temporary directory. Existing demo output directories must be empty.

The operator CLI supports `--runs-root`, `--ledger` and `--evidence-root` before subcommands. Defaults are checkout-local `runs/`, `data/` and `output/evidence/`. Set `GOALFLOW_EVIDENCE_ROOT` before process startup to override the evidence default. These outputs are generated at runtime and excluded from the release.

## Optional, unverified in this release

The OpenAI adapter remains in source but requires the optional `openai==3.35.1` SDK and your own credential/configuration. Historical attempt allowances do not authorize new studies. Old Google readiness probes were excluded from the public release; no Drive integration claim is made.

Paperclip extraction requires Node with type stripping. Restate setup is pinned to Apple Silicon macOS and its separate requirements file. Their code and provenance are retained, but neither optional backend was rerun for release validation. No new full three-backend comparison is authorized or needed.

Run the supported GoalFlow subset with `python -m scripts.validate_lifecycle`. The optional experiment runner creates new results; do not run it against retained history. Raw historical logs/databases are private. Aggregate `evidence` fields name original records that are intentionally omitted, not public file links. Historical accounting scripts expect complete original layouts and are not a public evidence-reproduction command.
