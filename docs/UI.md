# Operator surface

Draw the box first, then design how we interact with it.

The Day 1 responsive read-only shell establishes six primary areas: overview,
authority/policy, data/provenance, research/experiments, knowledge workspace and
local-helper status. Execution-disabled state is always visible. Service health is
not fabricated: API liveness means only that the API process responds; database
health comes from authenticated checks. The interface has no approval/trade buttons.

Future interactions: inspect an evidence-backed status → navigate to its provenance;
compare a requested policy against current limits → authenticated human decision;
review dataset completeness → inspect source manifest; inspect experiment results →
trace reproducible inputs. Design empty, stale, partial and error states before
adding actions. Keep irreversible actions separate and explicitly authorized.

Run `python -m uvicorn triad.api:app --host 127.0.0.1 --port 8000` inside the venv.
The API and shell are local development only; external access needs authentication,
TLS and authorization. Browser/API tests verify contracts; manual visual inspection
is separately recorded in the setup report when performed.
