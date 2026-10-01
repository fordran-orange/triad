import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace


def test_launcher_propagates_failure_without_a_console(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "tools/run_core_supervisor.py"
    spec = importlib.util.spec_from_file_location("quiet_supervisor", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "__file__", str(tmp_path / "tools/run_core_supervisor.py"))
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(subprocess, "run", run)
    assert module.main() == 7
    args, options = calls[0]
    assert args[-1] == str(tmp_path / "tools/ensure_core.ps1")
    assert "-Restart" not in args
    assert options["creationflags"] == 0x08000000
    assert options["stdin"] == subprocess.DEVNULL
    assert options["cwd"] == tmp_path
