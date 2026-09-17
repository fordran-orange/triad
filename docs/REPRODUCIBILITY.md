# Reproduction and portability

Run `python tools/research.py run <experiment-id>` from the project venv, or use Reproduce run in the research UI. Every run creates a new UUID/artifact folder and retains original inputs. Deterministic content hashing excludes incidental run IDs, start times and measured performance, but includes trades, equity, decisions and metrics. Repeated Parquet files can differ in run_id while their canonical results match exactly.

The run checks dataset version/timeframe, file hashes and current lab source hash against the immutable experiment. Git commit and Python/pandas/pyarrow versions are recorded. Later source changes require restoring compatible code or creating a new experiment, not overwriting old provenance.

Independent portable check:

```powershell
python tools/portable_research.py C:/Triad C:/Triad/data/manifests/<dataset-id>.json C:/Triad/research/experiments/<experiment-id>/runs/<run-id>/manifest.json
```

Only Python and pyarrow are needed. The script imports no Triad modules, opens no network/database connections, verifies checksums, reads dataset Parquet, trade/equity/decision Parquet and metrics/configuration JSON. Relative artifact paths resolve inside the supplied bundle root. Portable does not mean malicious files are safe to execute; the reader only reads data.


Review correction: new experiments record lab_source_hash_format=lf-v1. Source hashing normalizes CRLF to LF, matching Git checkout semantics while still detecting code edits. Pre-correction experiments/artifacts remain historical and are not rewritten to claim the corrected engine produced them. Use the corrected experiment listed in DAY4_REVIEW_FIXES.md.
