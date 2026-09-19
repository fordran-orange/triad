"""Build, install and smoke-test outside the checkout, without connecting to providers."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = Path(tempfile.mkdtemp(prefix="trading-core-package-"))
    wheels = destination / "wheels"
    target = destination / "installed"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            str(ROOT),
            "--no-deps",
            "--no-build-isolation",
            "-w",
            str(wheels),
        ],
        check=True,
        capture_output=True,
    )
    wheel = next(wheels.glob("*.whl"))
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(target), str(wheel)],
        check=True,
        capture_output=True,
    )
    code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import trading_core
assert Path(trading_core.__file__).is_relative_to(Path(sys.argv[1]))
from trading_core.api import app
from trading_core.resources import resource
from trading_core.control import Registry
from trading_core.support import CAPABILITIES
from products.triad.resources import product_resource
from products.aegis.server import app as aegis
from products.triad.server import app as triad
from fastapi.testclient import TestClient
assert len(Registry().agents)==4 and CAPABILITIES
for name in ['002_orchestration','003_autonomy','006_record_ownership','008_artifact_ownership','012_aegis_lineage','013_resource_allocations']:
    assert resource('infrastructure/postgres/'+name+'.sql').read_text()
assert product_resource('product.json').read_text()
for path in ['/core','/day2','/research','/settings/ai-providers','/assets/record-view.js','/assets/record-view.css','/core/integrations','/assets/integrations.js','/launch']:
    response=TestClient(app).get(path)
    assert response.status_code==200, path
assert TestClient(aegis).get('/aegis').status_code==200
for path in ['/triad/product','/triad/development','/triad/cycles','/triad/assets/cycles.js']:
    assert TestClient(triad).get(path).status_code==200, path
print('Clean installed package: Core, Aegis, config, SQL, HTML, JS and CSS passed')
"""
    env = {
        **os.environ,
        "TRADING_HOME": str(destination),
        "POSTGRES_PASSWORD": "unused-package-test",
        "NEO4J_PASSWORD": "unused-package-test",
        "CORE_PROVIDER_MONITOR": "0",
        "PYTHONUTF8": "1",
    }
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(target)],
        cwd=destination,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    print(result.stdout.strip())
    print("Installed evidence:", destination)


if __name__ == "__main__":
    main()
