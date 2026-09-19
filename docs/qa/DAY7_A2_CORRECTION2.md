# Day 7 A2 correction 2 — legacy promotion controls

Corrects the P1 finding preserved in DAY7_A2_CORRECTION_QA.md. Agent promotion resolves historical p2p ownership to current aegis before reading product pause controls. A successful, independently reviewed promotion issues its new grant/evidence under current canonical ownership while retaining the old immutable grant unchanged.

Root validation: promotion control regression, A2 adversarial context/encoding regressions and specialist-agent suite: **15 passed, 2 existing warnings, 30.96s**, exit0. Ruff passed. Evidence logs/day7-a2-correction3-tests.log/.exit. Fresh independent QA required. Production remains on Day6 until approval of this correction and live acceptance.
