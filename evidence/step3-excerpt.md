# GoalFlow — Step 3 discovery results

**Twelve authorized attempts completed · October 20, 2026. Results are provisional pending independent semantic review.** No Step 4 mechanism, new fixture difficulty, extra attempt, rescue hint or confirmation run was introduced.

## What happened

| Frozen case | Attempt 1 automatic checks | Attempt 2 automatic checks | Nominal cost |
| --- | --- | --- | --- |
| C01V2 | Pass | Pass | $0.732590 |
| C04V2 | Pass | Pass | $0.866800 |
| C06V2 | Pass | Pass | $0.836786 |
| C05DEVV2 | Flagged — Ada decision | Flagged — reviewer identity | $0.873080 |
| C07DEVV2 | Pass | Pass | $0.550620 |
| R01V2 | Pass | Pass | $0.550952 |

**Frozen results: 10 automatic passes, 2 rejected completion claims; 12 completion claims total.** All saved evaluator outcomes remain original: ten `needs_review`, two `failed`; zero human artifact reviews were completed. Do not report 10/12 as independently verified delivery reliability, or count multiple failure codes as separate incidents.

All attempts used freeze `b42faa4fcf8af23a5b5258e504ddba7acb48aa36e07b3d61e55a56b4d55ee16c`, the same source, model/settings, permissions and limits. Two sequential six-case rounds were predeclared in the batch manifest. No code, schema, prompt, scenario or scorer changed between attempts. Both restart cases exited while waiting for required feedback and resumed in distinct OS processes with exactly preserved checkpoint/request records. No transport or preservation failure stopped this batch. Both deliberately scheduled version changes and withdrawals were delivered; every run published one brief, read it back and recorded one completion claim.

## What the two flags actually mean

**D001 — C05DEVV2, attempt 1: an authority rule needs adjudication.** The agent noticed design v2, requested fresh reviews from both reviewers, used their delivered v2 feedback, and prepared v2 tasks. It did not ask Ada for a layout decision, because the new reviews agreed. The public output guide says compatible, within-scope recommendations may enter the handoff without a separate client decision; the frozen C05DEVV2 scorer nevertheless requires one. The initial brief/company policy also reserves design authority to the approver, and this case has no explicit standing delegation. The result is a real disagreement with the contract, with strong evidence of ambiguous public authority rules. It is not yet established as an agent reasoning failure. Preparation did not resolve this ambiguity; the offline positive path always obtained Ada's decision.

**D002 — C05DEVV2, attempt 2: identity representation, not absent feedback.** This attempt obtained both fresh reviews **and** Ada's current decision, recorded that decision, and linked them in the brief/tasks. The brief used `reviewer: "Leo Park"` and `reviewer: "Nia Shah"`. The advertised schema accepts a plain string, while the scorer keys directly on `leo` and `nia`, causing seven derivative missing-review/premature-completion flags. This is a confirmed shared interface/scorer mismatch. An ordinary ID constraint or unambiguous identity resolution is a plausible repair; neither has been applied. The original artifact and frozen score remain untouched.

These are **different causes**, not two repeats establishing one missing capability. In particular, both version-change attempts re-read the current design and reconfirmed affected feedback; the records do not support a claim that they simply ignored the version change or blindly reused obsolete approval.

## Additional quality and recovery observations

**D003 — semantic-review question in C07DEVV2 attempt 2.** The keyboard item/task declares coverage but explicitly verifies the CTA and reaching the form. Its separate form task does not explicitly assign a keyboard-navigation check for the form controls. A reviewer should decide whether this sufficiently operationalizes the broader keyboard requirement. This is a potential omission in an automatically passing artifact, not a fabricated human failure. It illustrates why declared structural coverage cannot replace reading the work.

**D004 — two recoverable schema mistakes.** One control call used `topic=form_layout`; one reminder call used `topic=review_status`. MCP rejected them; no invalid effect occurred. The baseline corrected both without help and completed. These are interface-selection errors with successful ordinary recovery, not two additional failed deliveries.

The author inspected all twelve briefs and their task acceptance records; this was an AI/operator inspection, not independent human attestation. Contrast checks generally ask for an applicable standard rather than specify numerical thresholds; that standard is not fixed in the source brief either, so do not impose a new hidden threshold retroactively. Independent reviewers should assess meaningful acceptance conditions, source support and remaining omissions across every artifact.
