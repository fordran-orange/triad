# Reviewed rollback

Every Change records work, proposal, branch, base/change/review/merge commits, files, check evidence, worker/reviewer, mode and status. The lineage UI opens both record detail and canonical work/graph history. A rollback must target a recorded merged autonomous change.

The operator's Prepare rollback action calls `/api/day3/changes/<id>/rollback`. Under the cycle lease and current daily budget, the broker creates a new WorkItem/isolated branch and executes a real Git revert of the original change commit. It records a new handoff and pending Change. A distinct reviewer checks the reverse diff under normal policy. Only exact reviewed approval can merge the rollback; human-review mode also requires explicit operator merge approval.

After merge, the original record becomes ROLLED_BACK and points to the rollback; its CycleSummary retains the rollback ID. Original commits/history are preserved. Conflicts, changed baseline, exhausted daily slots or rejected review block the operation. No force reset or automatic production rollback occurs. Integration tests prove actual file removal/reversal, commits, independent review and corrected original status in disposable repositories. Production demonstration changes remain intact.
