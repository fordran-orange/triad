"""Exercise Windows supervisors with controlled OS/network seams; never launch servers."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PS = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(PS is None, reason="Windows supervisor")


def run(tmp_path, script, setup="", args=(), env=None):
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    for name in ("ensure_core.ps1", "ensure_ollama.ps1", "install_core_supervisor.ps1"):
        shutil.copyfile(ROOT / "tools" / name, tools / name)
    wrapper = tmp_path / "probe.ps1"
    wrapper.write_text(
        setup + "\n& '" + str(tools / script) + "' " + " ".join(args)
        + "\nexit $LASTEXITCODE", encoding="utf-8"
    )
    values = os.environ.copy()
    for key in ("OLLAMA_URL", "OLLAMA_MODEL"):
        values.pop(key, None)
    values.update(env or {})
    return subprocess.run(
        [PS, "-NoProfile", "-File", str(wrapper)], capture_output=True,
        text=True, timeout=40, env=values, check=False,
    )


NO_START = "function Start-Process { throw 'UNEXPECTED_PROCESS_LAUNCH' }"
TAGS = "[pscustomobject]@{models=@([pscustomobject]@{name='qwen3:4b'})}"


def test_available_model_requires_no_launch(tmp_path):
    result = run(tmp_path, "ensure_ollama.ps1", NO_START +
                 "\nfunction Invoke-RestMethod { " + TAGS + " }")
    assert result.returncode == 0, result.stderr
    assert "no inference performed" in (tmp_path / "logs/ollama-supervisor.log").read_text()


@pytest.mark.parametrize(
    "case", ["missing_model", "occupied_port", "remote", "mismatch", "credential", "bad_uri"]
)
def test_configuration_failure_does_not_touch_process(tmp_path, case):
    setup = NO_START + "\nfunction Invoke-RestMethod { throw 'offline' }"
    env = {}
    if case == "missing_model":
        setup = NO_START + "\nfunction Invoke-RestMethod { [pscustomobject]@{models=@()} }"
    elif case == "occupied_port":
        setup += "\nfunction Get-NetTCPConnection { [pscustomobject]@{OwningProcess=123} }"
    elif case == "remote":
        env["OLLAMA_URL"] = "http://example.com:11434"
    elif case == "credential":
        env["OLLAMA_URL"] = "http://user:secret-sentinel@127.0.0.1:11434"
    elif case == "bad_uri":
        env["OLLAMA_URL"] = "http://[secret-sentinel"
    else:
        env["OLLAMA_URL"] = "http://127.0.0.1:11435"
    result = run(tmp_path, "ensure_ollama.ps1", setup, env=env)
    assert result.returncode == 1
    log = (tmp_path / "logs/ollama-supervisor.log").read_text()
    assert "recovery failed" in log
    assert "UNEXPECTED_PROCESS_LAUNCH" not in log
    assert "secret-sentinel" not in log


def test_start_is_hidden_and_preserves_user_model_store(tmp_path):
    capture = tmp_path / "launch.json"
    setup = """$script:calls=0
function Invoke-RestMethod {
 $script:calls++; if ($script:calls -eq 1) {throw 'offline'}; TAGS
}
function Get-NetTCPConnection { return $null }
function Start-Process {
 param($FilePath,$ArgumentList,$WindowStyle,[switch]$PassThru,$WorkingDirectory,
       $RedirectStandardOutput,$RedirectStandardError)
 @{file=$FilePath; args=$ArgumentList; window=$WindowStyle;
   models=$env:OLLAMA_MODELS; endpoint=$env:OLLAMA_HOST} |
   ConvertTo-Json | Set-Content -LiteralPath 'CAPTURE'
 [pscustomobject]@{Id=999}
}
""".replace("TAGS", TAGS).replace("CAPTURE", str(capture))
    result = run(tmp_path, "ensure_ollama.ps1", setup)
    assert result.returncode == 0, result.stderr
    launch = json.loads(capture.read_text(encoding="utf-8-sig"))
    assert launch["window"] == "Hidden"
    assert launch["args"] == "serve"
    assert Path(launch["file"]).name == "ollama.exe"
    assert Path(launch["file"]).is_file()
    assert launch["endpoint"] == "127.0.0.1:11434"
    assert launch["models"] == os.environ.get("OLLAMA_MODELS")


def test_live_core_still_checks_ollama_without_core_restart(tmp_path):
    setup = NO_START + """
function Invoke-RestMethod {
 param($Uri)
 if ($Uri -like '*/health/live') {return [pscustomobject]@{status='ok'}}
 throw 'offline'
}
function Get-NetTCPConnection { [pscustomobject]@{OwningProcess=123} }
function docker { throw 'LIVE_CORE_MUST_NOT_RESTART_DATABASES' }
"""
    result = run(tmp_path, "ensure_core.ps1", setup)
    assert result.returncode == 1
    assert "Core healthy" in (tmp_path / "logs/core-supervisor.log").read_text()
    assert "port is occupied" in (tmp_path / "logs/ollama-supervisor.log").read_text()


def test_task_has_logon_and_indefinite_retry_without_registration(tmp_path):
    result = run(
        tmp_path, "install_core_supervisor.ps1",
        "function Register-ScheduledTask { throw 'MUST_NOT_REGISTER' }", ["-ValidateOnly"],
    )
    assert result.returncode == 0, result.stderr
    task = json.loads(result.stdout)
    assert task["Principal"]["LogonType"] == 3
    assert task["Principal"]["RunLevel"] == 0
    assert task["Settings"]["MultipleInstances"] == 2
    assert task["Settings"]["RestartCount"] == 3
    assert len(task["Triggers"]) == 2
    periodic = next(x for x in task["Triggers"] if x.get("Repetition", {}).get("Interval"))
    assert periodic["Repetition"]["Interval"] == "PT5M"
    assert not periodic["Repetition"]["Duration"]
    assert "-WindowStyle Hidden" in task["Actions"][0]["Arguments"]
