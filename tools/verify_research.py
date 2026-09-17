"""Read-only verification of the recorded Day 4 laboratory mission."""

import json
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from triad.brain import Brain
from triad.lab.contracts import DatasetManifest
from triad.lab.service import Laboratory, source_hash
from triad.settings import ROOT


def main():
    lab = Laboratory()
    demo = json.loads((ROOT / "logs/research-demo.json").read_text())
    experiment = demo["experiment"]
    assert experiment["environment"]["lab_source_sha256"] == source_hash()
    datasets = [demo["dataset"], *demo["derived"]]
    for data in datasets:
        manifest = DatasetManifest.model_validate(data)
        frame = lab.archive.load(manifest)
        assert len(frame) == data["row_count"] and data["quality_status"] == "PASS"
        assert data["mode"] == "FIXTURE"
    runs = [
        r
        for r in lab.ledger.records("BacktestRun")
        if r["experiment_id"] == experiment["experiment_id"]
    ]
    assert len(runs) >= 2 and len({r["content_hash"] for r in runs}) == 1
    portable = []
    for run in runs:
        assert run["status"] == "COMPLETED"
        assert lab.host.store.get(run["work_item_id"]).status == "COMPLETED"
        command = [
            sys.executable,
            str(ROOT / "tools/portable_research.py"),
            str(ROOT),
            str(ROOT / f"data/manifests/{experiment['dataset_id']}.json"),
            str(
                ROOT
                / f"research/experiments/{experiment['experiment_id']}/runs/{run['run_id']}/manifest.json"
            ),
        ]
        portable.append(json.loads(subprocess.check_output(command, text=True)))
    reviews = [
        r
        for r in lab.ledger.records("ResearchReview")
        if r["experiment_id"] == experiment["experiment_id"]
    ]
    assert len(reviews) == len(runs)
    assert all(
        r["decision"] == "ACCEPT_RESULT" and r["mode"] == "HOST_VERIFIER_NOT_MODEL" for r in reviews
    )
    queries = {
        "raw_to_base": "MATCH (:RawDataset)-[:NORMALIZED_INTO]->(d:Dataset {id:$dataset}) RETURN count(d) AS n",
        "derived_from_base": "MATCH (:Dataset {id:$dataset})-[:DERIVED_INTO]->(d:Dataset) RETURN count(d) AS n",
        "dataset_to_experiment": "MATCH (:Dataset {id:$dataset})-[:USED_BY]->(e:Experiment {id:$experiment}) RETURN count(e) AS n",
        "experiment_to_commit": "MATCH (:Experiment {id:$experiment})-[:SUPPORTED_BY]->(c:Commit) RETURN count(c) AS n",
        "runs_in_experiment": "MATCH (r:BacktestRun)-[:PART_OF]->(:Experiment {id:$experiment}) RETURN count(r) AS n",
        "reviews_of_runs": "MATCH (:Experiment {id:$experiment})<-[:PART_OF]-(r:BacktestRun)-[:HAS_REVIEW]->(v:ResearchReview) RETURN count(v) AS n",
        "claim_evidence": "MATCH (:Claim)-[:SUPPORTED_BY]->(r:BacktestRun)-[:PART_OF]->(:Experiment {id:$experiment}) RETURN count(r) AS n",
    }
    graph = {}
    with Brain(lab.host.store).driver() as driver, driver.session() as session:
        for name, query in queries.items():
            graph[name] = session.run(
                query, dataset=experiment["dataset_id"], experiment=experiment["experiment_id"]
            ).single()["n"]
    assert graph == dict(zip(queries, [1, 5, 1, 1, len(runs), len(runs), 2], strict=True))
    endpoints = {}
    for path in ("/api/status", "/api/foundation", "/api/research/dashboard"):
        with urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=30) as response:
            endpoints[path] = json.load(response)
    assert endpoints["/api/foundation"]["live_trading_authority"] is False
    assert all(
        endpoints["/api/status"][name]["status"] == "up"
        for name in ("postgres", "timescale", "neo4j", "ollama", "git", "backend")
    )
    assert len(endpoints["/api/research/dashboard"]["datasets"]) >= 6
    projection = lab.host.store.projection_status()
    assert projection["pending"] == projection["errors"] == 0
    baseline = json.loads((ROOT / "logs/day3-verification.json").read_text())
    assert lab.ledger.totals() == baseline["budgets"]
    control = lab.ledger.control()
    assert not control["paused"] and not control["killed"]
    tests = ET.parse(ROOT / "logs/day4-research-tests.xml").getroot().find("testsuite").attrib
    assert int(tests["tests"]) >= 177 and all(
        int(tests[k]) == 0 for k in ("failures", "errors", "skipped")
    )
    storage = {
        folder: sum(p.stat().st_size for p in (ROOT / folder).rglob("*") if p.is_file())
        for folder in ("data/raw", "data/canonical", "data/manifests", "research/experiments")
    }
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "tests": tests,
        "dataset_ids": [d["dataset_id"] for d in datasets],
        "experiment_id": experiment["experiment_id"],
        "run_ids": [r["run_id"] for r in runs],
        "content_hash": runs[0]["content_hash"],
        "portable": portable,
        "graph": graph,
        "projections": projection,
        "services_up": True,
        "model_budgets_unchanged": True,
        "storage_bytes": storage,
        "run_resources": [
            {k: r[k] for k in ("run_id", "runtime", "peak_memory_bytes", "storage_bytes")}
            for r in runs
        ],
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "working_tree": subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ).strip(),
    }
    (ROOT / "logs/day4-research-verification.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n"
    )
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
