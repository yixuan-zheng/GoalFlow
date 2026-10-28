# Final release validation — October 28, 2026

All commands ran against clean copies of the packaged release source, using `requirements-offline.lock` in fresh environments. No code assertion was removed or weakened. The historical verifier was narrowed to the documented public evidence subset because private raw stores/logs were excluded; baseline and lifecycle tests are unchanged from Phase 1.

| Environment | Baseline | Lifecycle | Demo | Evidence and upstream blobs | pip check |
| --- | --- | --- | --- | --- | --- |
| macOS, Python 3.13.12, relocated clean copy | 93 passed in 5.99s | 38/38 | Passed | Passed | Passed |
| Linux official Python 3.13 slim container | 93 passed in 6.40s | 38/38 | Passed | Passed | Passed |
| Linux official Python 3.12 slim container | 93 passed in 6.50s | 38/38 | Passed | Passed | Passed |

The Linux candidate was mounted read-only, copied to a fresh container work directory, and dependencies installed from the lockfile. The container ran the same test/demo/evidence commands as the configured CI matrix. This is local Linux execution, not a GitHub Actions result or x86 replication.

The two Linux image digests were:

- Python 3.13: `sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb`
- Python 3.12: `sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159`

Each demo used distinct subprocesses and passed automatic evaluation, while leaving `artifact_review=pending`, `outcome=needs_review`, `passed=false`. Its separate revision sequence passed 94 assertions. Workers and provider are scripted; there were no paid requests or live workplace changes.

Evidence verification checks seven unchanged historical records/excerpts and three vendored Paperclip Git blob identities, including its license. It confirms the 112-cell saved result table, not fresh execution of those three backends. `docs/VALIDATED_INPUTS.json` identifies unchanged executable/configuration/fixture inputs checked after clean-copy validation. Final documentation and audit outputs are covered by the final file inventory.

## GitHub Actions

The public repository is [yixuan-zheng/GoalFlow](https://github.com/yixuan-zheng/GoalFlow). The initial publication commit `7f4c8a5a2681c06e42fd65599641124b8e361b94` passed the actual hosted [Offline validation run](https://github.com/yixuan-zheng/GoalFlow/actions/runs/40780679105). Both Linux jobs completed successfully:

| Hosted job | Baseline | Lifecycle | Demo | Historical evidence |
| --- | --- | --- | --- | --- |
| Python 3.12 | 93 passed, 16.03s | 38/38 | Passed; needs_review; 94 revision assertions | Seven records and upstream Git blobs verified |
| Python 3.13 | 93 passed, 15.08s | 38/38 | Passed; needs_review; 94 revision assertions | Seven records and upstream Git blobs verified |

These timings identify the observed runs; they are not a performance comparison. [Latest workflow results](https://github.com/yixuan-zheng/GoalFlow/actions/workflows/offline.yml) track subsequent publication-metadata commits. Every push triggers the same matrix. Tests, assertions, lockfile and historical evidence are unchanged from the approved candidate.

The repository API and a credential-free clone confirmed public access. The clone matched all 209 initial candidate files byte-for-byte. README local link targets resolve, and GitHub's public page includes the Mermaid architecture markup. Licensing and upstream notices are preserved.

GitHub emitted nonblocking notices about Node 20 action runtime migration and the ubuntu-latest image transition; both jobs succeeded. No portability/build repair was necessary.

## Optional and historical limitations

OpenAI execution, Drive integration, optional Restate/Paperclip comparison execution and hosted-model studies were not validated in this release. Historical human semantic review remains unresolved. No Step 4 intervention or new general framework is claimed. macOS Python 3.12 and other operating systems were not freshly tested. Hosted Ubuntu runner execution supplements the earlier local container checks.
