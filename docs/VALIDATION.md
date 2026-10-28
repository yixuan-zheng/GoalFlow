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

`.github/workflows/offline.yml` defines Linux Python 3.12/3.13 jobs. An authenticated repository search returned no accessible GoalFlow repository. None was created or pushed. Therefore Actions has **not run**, no workflow URL exists, and this remains an explicit publication gate after separate authorization. Local Docker results do not satisfy that hosted-CI gate.

## Optional and historical limitations

OpenAI execution, Drive integration, optional Restate/Paperclip comparison execution and hosted-model studies were not validated in this release. Historical human semantic review remains unresolved. No Step 4 intervention or new general framework is claimed. macOS Python 3.12, other operating systems and x86 Linux were not freshly tested.
