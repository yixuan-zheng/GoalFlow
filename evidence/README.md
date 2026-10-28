# Curated historical evidence

These records preserve findings; they are not complete raw studies or fresh experiment outputs.

- [Step 3 excerpt](step3-excerpt.md): exact original report lines 1–34. Ten automatic passes (`needs_review`), two frozen failures; authority ambiguity and reviewer-identity mismatch are separate causes. Human review remains unresolved.
- [Separate AI adjudication excerpt](adjudication-excerpt.md): exact original summary lines 1–29. One material keyboard-accessibility omission; no repeated shared failure mechanism. AI review is not human adjudication.
- [Lifecycle raw result table](lifecycle/results.json): unchanged 112-cell saved result list, including scenario names, assertion counts and elapsed times. Times are historical observations, not a performance benchmark.
- [Lifecycle decision](lifecycle/decision.json): unchanged 8.8% reduction versus the smallest comparator; 30% gate missed; preserve prototype and stop framework expansion.
- [Accounting](lifecycle/code-accounting.json), [metadata](lifecycle/metadata.json), [frozen specification](lifecycle/SPEC.md): unchanged source accounting, run/source hashes and predeclared contract.

`manifest.json` records hashes, excerpt ranges and original full-report hashes. `original-checksum-subset.json` retains the applicable entries from the original lifecycle checksum inventory. Excerpts omit whole subsequent sections with private paths; no line within an excerpt was rewritten. Missing raw traces and databases remain private and limit independent re-adjudication.

`python -m scripts.verify_evidence` verifies this subset and the vendored Paperclip Git blob identities. It does not prove authenticity through a trusted signature, rerun experiments, rescore artifacts, close human review or reproduce every historical assertion. Fresh 93-test/38-cell results are reported separately in the validation document.
