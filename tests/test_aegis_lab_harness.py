"""Optimization Lab v2, Phase 2, Task 1: the scratch harness. `AEGIS_DATA_ROOT` moves the run
store and nothing else, `/health/live` names the code and the store a worker serves, the walk
refuses its restart and trash items unless it drives a scratch worker on a scratch root, and the
scratch launcher names the product ports only to refuse them."""

import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import products.aegis
import pytest
from fastapi.testclient import TestClient
from products.aegis import api, server
from products.aegis.data import DATA_ROOT, ArchiveStore
from products.aegis.preferences import Preferences
from products.aegis.runs import JsonRunRepository, aegis_data_root

pytestmark = pytest.mark.aegis

CHECKOUT = Path(__file__).resolve().parents[1]
SCRIPT = CHECKOUT / "tools" / "start_aegis_scratch.ps1"
PRODUCT_PORT_CHECK = re.compile(r"^\s*if \(\$Port -in @\(8101, 8102\)\)")

sys.path.insert(0, str(Path(__file__).resolve().parent / "products" / "aegis"))
from browser_workstation import PRODUCT_ROOT, Acceptance, destructive_items_allowed


def test_data_root_override_default_unchanged(monkeypatch):
    monkeypatch.delenv("AEGIS_DATA_ROOT", raising=False)
    assert aegis_data_root() == DATA_ROOT / "data" / "aegis"
    assert JsonRunRepository().root == DATA_ROOT / "data" / "aegis"
    assert Preferences().path.parent == DATA_ROOT / "data" / "aegis"
    monkeypatch.setenv("AEGIS_DATA_ROOT", "")  # set but empty reads as unset
    assert JsonRunRepository().root == DATA_ROOT / "data" / "aegis"


def test_data_root_override_moves_the_store_only(tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    monkeypatch.setenv("AEGIS_DATA_ROOT", str(scratch))
    assert aegis_data_root() == scratch
    assert JsonRunRepository().root == scratch
    assert Preferences().path.parent == scratch
    assert api.get_learned(JsonRunRepository()).folder.is_relative_to(scratch)
    assert ArchiveStore().root == DATA_ROOT  # the archives stay where they are
    assert JsonRunRepository(tmp_path / "given").root == tmp_path / "given"  # an argument wins


def test_health_live_reports_app_and_data_root(monkeypatch):
    monkeypatch.setattr(server, "Store", lambda **_: SimpleNamespace(list_work=list))
    body = TestClient(server.app).get("/health/live").json()
    assert body["status"] == "ok" and body["product"] == "aegis"
    # The checkout holding this test: a run importing another checkout's app fails here.
    app_root = CHECKOUT / "app"
    assert Path(body["app_root"]) == app_root
    assert Path(products.aegis.__file__).resolve().is_relative_to(app_root)
    assert body["data_root"] == str(aegis_data_root())


def test_walk_refuses_destructive_items_on_product_root(tmp_path):
    pid = tmp_path / "aegis-scratch.pid"
    product = Path("C:/Triad/data/aegis")
    scratch = PRODUCT_ROOT.with_name("aegis-scratch")  # a sibling of the product store
    assert (
        destructive_items_allowed(
            PRODUCT_ROOT, PRODUCT_ROOT, port=8102, pid_file=None, worker_data_root=PRODUCT_ROOT
        )
        is False
    )
    assert (
        destructive_items_allowed(
            product, PRODUCT_ROOT, port=8102, pid_file=pid, worker_data_root=product
        )
        is False
    )
    assert (
        destructive_items_allowed(
            product, PRODUCT_ROOT, port=8103, pid_file=pid, worker_data_root=product
        )
        is False
    )
    assert (
        destructive_items_allowed(
            scratch, PRODUCT_ROOT, port=8103, pid_file=pid, worker_data_root=scratch
        )
        is True
    )
    assert (
        destructive_items_allowed(
            scratch, PRODUCT_ROOT, port=8103, pid_file=pid, worker_data_root=tmp_path
        )
        is False
    )
    assert (
        destructive_items_allowed(
            scratch, PRODUCT_ROOT, port=8103, pid_file=pid, worker_data_root=None
        )
        is False
    )
    assert (
        destructive_items_allowed(
            scratch, PRODUCT_ROOT, port=8103, pid_file=None, worker_data_root=scratch
        )
        is False
    )

    def walk(**overrides) -> Acceptance:
        given = {
            "data_root": PRODUCT_ROOT,
            "pid_file": None,
            "port": 8102,
            "worker_data_root": PRODUCT_ROOT,
        }
        page = SimpleNamespace(on=lambda *a, **k: None)
        return Acceptance(page, "http://127.0.0.1:8102/aegis/", "stamp", **(given | overrides))

    product_walk = walk()
    with pytest.raises(RuntimeError, match=r"^refused: --data-root is the product root"):
        product_walk.require_scratch_root()
    assert product_walk.results == []  # the item wrapper records the refusal, never the guard
    with pytest.raises(RuntimeError, match=r"^refused: the worker on port 8102 is the product"):
        walk(data_root=scratch, pid_file=pid, worker_data_root=scratch).require_scratch_root()
    with pytest.raises(RuntimeError, match=r"^refused: the worker's data_root differs"):
        walk(data_root=scratch, pid_file=pid, port=8103).require_scratch_root()
    allowed = walk(data_root=scratch, pid_file=pid, port=8103, worker_data_root=scratch)
    assert allowed.require_scratch_root() is None and allowed.results == []
    with pytest.raises(RuntimeError, match=r"^restart needs --pid-file"):
        walk(data_root=scratch, port=8103, worker_data_root=scratch).restart_worker()


def _block_end(lines: list[str], start: int) -> int:
    depth = 0
    for index in range(start, len(lines)):
        depth += lines[index].count("{") - lines[index].count("}")
        if depth == 0 and index > start:
            return index
    raise AssertionError(f"the block opened at line {start + 1} never closes")


def test_scratch_launcher_never_names_the_product_port(tmp_path):
    text = SCRIPT.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert "start_product" not in text
    # One Stop-Process, inside the -Stop branch, on the pid the script read from -PidFile.
    stops = [i for i, line in enumerate(lines) if "Stop-Process" in line]
    assert len(stops) == 1, [lines[i] for i in stops]
    (branch,) = [i for i, line in enumerate(lines) if re.match(r"^\s*if \(\$Stop\) \{", line)]
    assert branch < stops[0] < _block_end(lines, branch)
    read = {
        found.group(1)
        for line in lines
        if (found := re.match(r"^\s*\$(\w+) = .*Get-Content .*\$PidFile\b", line))
    }
    assert len(read) == 1, read
    assert re.search(rf"-Id \${read.pop()}\b", lines[stops[0]]), lines[stops[0]]
    # The product ports appear only in the refusal and the throw that follows it.
    checks = [i for i, line in enumerate(lines) if PRODUCT_PORT_CHECK.match(line)]
    assert len(checks) == 1, checks
    assert lines[checks[0] + 1].strip() == 'throw "refused: port $Port is a product port"'
    for index, line in enumerate(lines):
        if "8101" in line or "8102" in line:
            assert index in (checks[0], checks[0] + 1), line
    store_refusal = 'throw "refused: -DataRoot is the product store"'
    (store_check,) = [i for i, line in enumerate(lines) if store_refusal in line]
    (port_check,) = [i for i, line in enumerate(lines) if line == "Assert-ScratchPort"]
    (listening,) = [i for i, line in enumerate(lines) if "Get-NetTCPConnection -LocalPort" in line]
    assert store_check < port_check < listening  # the store refusal runs before the port checks
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    refused_pid = tmp_path / "refused.pid"
    refused = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(SCRIPT), "-Port", "8102"]
        + ["-DataRoot", str(tmp_path), "-PidFile", str(refused_pid)],
        capture_output=True,
        text=True,
        cwd=CHECKOUT,
        timeout=120,
        check=False,
    )
    assert refused.returncode != 0, refused.stdout
    assert "refused: port 8102 is a product port" in refused.stdout + refused.stderr
    assert not refused_pid.exists()
    # The product store is refused before the port checks: a scratch worker live on 8103 must
    # not turn this into a port-in-use refusal.
    store_pid = tmp_path / "refused-store.pid"
    store = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(SCRIPT), "-Port", "8103"]
        + ["-DataRoot", "C:\\Triad\\data\\aegis", "-PidFile", str(store_pid)],
        capture_output=True,
        text=True,
        cwd=CHECKOUT,
        timeout=120,
        check=False,
    )
    assert store.returncode != 0, store.stdout
    assert "refused: -DataRoot is the product store" in store.stdout + store.stderr
    assert not store_pid.exists()
    nothing = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(SCRIPT), "-Stop"]
        + ["-PidFile", str(tmp_path / "none.pid")],
        capture_output=True,
        text=True,
        cwd=CHECKOUT,
        timeout=120,
        check=False,
    )
    assert nothing.returncode == 0, nothing.stdout + nothing.stderr
    assert "nothing to stop" in nothing.stdout
