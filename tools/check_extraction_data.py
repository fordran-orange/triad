"""Historical artifacts, deterministic engine outputs, and reversible migration proof."""
import hashlib
import json
import subprocess
from pathlib import Path
from types import ModuleType
from trading_core.settings import ROOT, Settings
from trading_core.store import Store
from trading_core.ledger import Ledger
from trading_core.research.service import Laboratory, source_hash
from trading_core.research.contracts import Experiment, DatasetManifest
from trading_core.research.engine import run_engine


def main():
    manifest = json.loads((ROOT / "backups/day5a-20260919/manifest.json").read_text())
    changed = [name for name, expected in manifest["artifacts"].items()
               if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != expected]
    assert not changed, changed
    restored = Store(Settings(postgres_db="core_baseline_restore"))
    with restored.connect() as conn:
        before = conn.execute("SELECT id,payload FROM core.work_items ORDER BY id").fetchall()
    restored.migrate(); Ledger(restored).initialize()
    # A rollback leaves additive owner columns intact for evidence preservation.
    with restored.connect() as conn:
        for name in ("006_record_ownership.down", "005_core_namespaces.down", "005_core_namespaces", "006_record_ownership", "008_artifact_ownership"):
            conn.execute((ROOT/f"infrastructure/postgres/{name}.sql").read_text())
        after = conn.execute("SELECT id,payload FROM core.work_items ORDER BY id").fetchall()
    assert before == after
    current = Store()
    with current.connect() as conn:
        ids = {r['id'] for r in conn.execute("SELECT id FROM core.work_items").fetchall()}
    assert {r['id'] for r in before} <= ids
    # Execute the original engine from the preserved commit against the same
    # canonical frame/experiment. Do not alter historical source fingerprints.
    baseline = subprocess.run(["git","show","base/day5a-complete:app/triad/lab/engine.py"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    old = ModuleType("baseline_engine")
    exec(compile(baseline, "baseline_engine", "exec"), old.__dict__)
    lab = Laboratory()
    experiments = lab.ledger.records("Experiment", 1000)
    compared=[]
    for record in experiments:
        if record['id'] not in {p.name for p in (ROOT/'backups/day5a-20260919/restored-artifacts/research/experiments').iterdir() if p.is_dir()}:
            continue
        exp = Experiment.model_validate({k:v for k,v in record.items() if k in Experiment.model_fields})
        dataset = lab.model("DatasetManifest", exp.dataset_id, DatasetManifest)
        frame = lab.archive.load(dataset)
        a,b = old.run_engine(frame, exp), run_engine(frame, exp)
        assert a == b, exp.experiment_id
        compared.append({'experiment_id':exp.experiment_id,'content_hash':b['content_hash'],'historical_source_hash':exp.environment['lab_source_sha256']})
    assert compared, "No preserved deterministic experiment was exercised"
    report={'historical_artifacts_unchanged':len(manifest['artifacts']), 'historical_work_ids_preserved':len(before), 'migration_up_down_up':'PASS','deterministic_experiments':compared,'new_source_hash':source_hash()}
    (ROOT/'logs/extraction-data.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
