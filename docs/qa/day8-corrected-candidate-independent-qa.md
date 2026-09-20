# Corrected Research Readiness candidate — bounded independent UI audit

**CHANGES_REQUIRED** at exact isolated candidate c4d518ed2b87547428be711742f3596cba39eb08, work d61d0ce4-78a4-48eb-9b0a-49d2eb1a557b. Reviewer /root/day6_qa_a. Candidate remains unmerged and the failed native QA is not replaced by this report.

P2: The successful evaluation branch accepts any object with a defined status property. Actual candidate JS run offline accepts {status:null}, {status:"READY"} without request/checks/evidence, and {status:"NOT_A_CORE_STATUS"}, then announces "Evaluation returned by Core." The READY-only malformed payload is displayed as Status:READY. Validate a recognized non-null status and the authoritative minimum envelope, including request identity and expected types, before presenting a Core result. Missing evidence must remain unavailable/unknown. The trusted reference packet correction will supply the contract needed for this validation.

The previous null/empty-object/array cases now fail readably. All request controls are disabled during the pending POST, preventing the ordinary input-edit race reported by native QA. Exact navigation links are present. Rendering remains text-only in inspected source.

The ignored Node DOM harness executes actual candidate JS with stubbed responses and no network/browser; six payload cases ran successfully as an adversarial reproduction. This is not browser/mobile or full provider QA. Current worktree contents match candidate Git content after line-ending normalization; exact raw Git hashes and evidence hashes are in the JSON. No source edits, inference, database writes, merge or schedule action occurred. Retain this required correction for the next authorized provider attempt after quota recovery.
