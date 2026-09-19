# Timestamp correction — controlled lifecycle ingestion

Independent QA on frozen99dd242 reproduced direct typed lifecycle-record ingestion bypasses for a worker and a foreign product. The original report and failing evidence are preserved. Public Store.add_record now rejects HandoffLifecycle; only the validated handoff transition method writes events after checking target ownership and assigned receiver. The read overlay additionally joins canonical handoff identity, owner, work ID, receiver and permitted phase, so an unrelated or historical invalid event cannot override another handoff.

Root corrected tests:7passed12.73s including independent worker/foreign-product regressions and actual append-only delivery lifecycle. Independent correction review required. Resource runtime wiring in other files is separate pending work, excluded from this correction.
