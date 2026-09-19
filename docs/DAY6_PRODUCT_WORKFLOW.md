# Day 6 product workflow

The operator-authorized single-cycle entry point is:

```powershell
.\.venv\Scripts\python.exe tools/run_product_cycle.py --operator-authorized
```

This explicitly invokes one bounded inspect → select → approve → build → separate QA → merge cycle. It does not enable scheduling. Core capabilities must already have independent passing QA and be adopted. The protected Git baseline must be clean `main` before the build.

Read-only inspection checkpoints can resume using `--mission ID`. Once a build has created an isolated worktree, an interrupted attempt requires explicit reconciliation; it is never blindly replayed. A failed QA retains its worktree and first-class QARun. Correct it through a new `Development.build(..., correction=required_changes)` assignment and call `qa` again before `merge`. Corrections consume the existing governed improvement/run budgets. No model-returned verdict can directly invoke a merge.

The old real rotation stage is closed to new implementations because it lacks a separate QA WorkItem. Historical simulated tests and read-only history remain available. Historical real changes with a Git diff require the new quality workflow before merge.

The product dashboard at `/triad/development` shows canonical evidence and only serves merged text artifacts whose bytes still match the independent review. Core provider administration remains in Core. Research findings and model output are displayed as text, never executable HTML. P2P, exchange policy and trading authority are unchanged.
