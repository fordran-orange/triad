"""The Core supervisor's Docker dependency pass (docs/CORE_DEPENDENCY_PORTS_AFTER_REBOOT.md,
Option C2): a bounded wait for the Docker engine, compose's stderr timestamped in the supervisor
log, and the Windows excluded-port table beside a failed dependency start. The real PowerShell
runs with `docker`, `netsh`, the web and the clock mocked; no container, engine or Core starts."""

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PS = shutil.which("powershell.exe")
pytestmark = [pytest.mark.skipif(PS is None, reason="Windows supervisor"), pytest.mark.core]

TIMESTAMPED = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
TAGS = "[pscustomobject]@{models=@([pscustomobject]@{name='qwen3:4b'})}"
# Ollama answers and Core is down, so the pass reaches the dependency step at once.
CORE_DOWN = (
    "function Invoke-RestMethod { param($Uri, $TimeoutSec, $MaximumRedirection)\n"
    " if ($Uri -like '*/health/live') { throw 'down' }\n"
    " " + TAGS + " }\n"
    "function Get-NetTCPConnection { return $null }\n"
    "function Start-Process { throw 'UNEXPECTED_PROCESS_LAUNCH' }\n"
    "function Start-Sleep { param($Seconds, $Milliseconds) }\n"
)
ENGINE_DOWN = (
    "function docker { param([Parameter(ValueFromRemainingArguments=$true)]$Arguments)\n"
    " if ($Arguments[0] -eq 'compose') { throw 'COMPOSE_MUST_NOT_RUN_WITHOUT_AN_ENGINE' }\n"
    " cmd /c exit 1 }\n"
)
NETSH = (
    "function netsh { 'Protocol tcp Port Exclusion Ranges'; ''; 'Start Port    End Port';"
    " '----------    --------'; '      5357        5357'; '     49152       49251     RANGE_SENTINEL';"
    " '     50000       50059     *' }\n"
)


def run(tmp_path, setup, args=()):
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    for name in ("ensure_core.ps1", "ensure_ollama.ps1"):
        shutil.copyfile(ROOT / "tools" / name, tools / name)
    supervisor = tools / "ensure_ollama.ps1"
    supervisor.write_text(
        supervisor.read_text().replace(
            "$python = Join-Path $TriadRoot '.venv/Scripts/python.exe'",
            "$python = '" + sys.executable + "'",
        )
    )
    (tools / "resolve_provider.py").write_text("print('unused')")
    # Core's launcher is a seam too: the pass must reach it only after the dependencies are up.
    (tools / "start_backend.ps1").write_text(
        "param([int]$Port, [switch]$CoreOnly)\n"
        "Add-Content -LiteralPath '"
        + str(tmp_path / "launched.txt")
        + '\' -Value "$Port $CoreOnly"\n'
        "exit 0\n"
    )
    wrapper = tmp_path / "probe.ps1"
    wrapper.write_text(
        setup
        + "\n& '"
        + str(tools / "ensure_core.ps1")
        + "' "
        + " ".join(args)
        + "\nexit $LASTEXITCODE",
        encoding="utf-8",
    )
    values = os.environ.copy()
    for key in ("OLLAMA_URL", "OLLAMA_MODEL"):
        values.pop(key, None)
    return subprocess.run(
        [PS, "-NoProfile", "-File", str(wrapper)],
        capture_output=True,
        text=True,
        timeout=60,
        env=values,
        check=False,
    )


def log_lines(tmp_path):
    return (tmp_path / "logs/core-supervisor.log").read_text(encoding="utf-8").splitlines()


def test_a_missing_engine_is_waited_for_then_named_without_running_compose(tmp_path):
    """Docker Desktop not running is the failure every logged boot had; the pass now waits a
    bounded time for the engine and then says so, instead of compose's pipe error landing
    untimestamped in the launcher log."""
    started = time.monotonic()
    result = run(tmp_path, CORE_DOWN + ENGINE_DOWN, ["-EngineWaitSeconds", "1"])
    assert result.returncode == 1, result.stderr
    assert time.monotonic() - started < 30
    lines = log_lines(tmp_path)
    assert all(TIMESTAMPED.match(line) for line in lines), lines
    assert any(
        "waiting up to 1 s" in line and "Docker engine unavailable" in line for line in lines
    ), lines
    assert any(
        "Docker Desktop is not running" in line and "recovery failed" in line for line in lines
    ), lines
    assert not any("COMPOSE_MUST_NOT_RUN" in line for line in lines), lines
    assert not (tmp_path / "launched.txt").exists()


def test_a_failed_compose_logs_its_stderr_and_the_excluded_port_table(tmp_path):
    """A blocked published port and a missing engine read identically today. Compose's own words
    and Windows' excluded-port table now sit, timestamped, next to the failure."""
    engine_up_compose_fails = (
        "function docker { param([Parameter(ValueFromRemainingArguments=$true)]$Arguments)\n"
        " if ($Arguments[0] -eq 'compose') {\n"
        '  cmd /c "echo Error response from daemon: Ports are not available BIND_SENTINEL 1>&2 & exit 1"\n'
        "  return }\n"
        " cmd /c exit 0 }\n"
    )
    result = run(tmp_path, CORE_DOWN + engine_up_compose_fails + NETSH)
    assert result.returncode == 1, result.stderr
    lines = log_lines(tmp_path)
    assert all(TIMESTAMPED.match(line) for line in lines), lines
    assert any("compose:" in line and "BIND_SENTINEL" in line for line in lines), lines
    assert any("excluded TCP port ranges" in line and "RANGE_SENTINEL" in line for line in lines), (
        lines
    )
    assert any("dependency startup failed (1)" in line for line in lines), lines
    assert not any("Docker Desktop is not running" in line for line in lines), lines
    assert not (tmp_path / "launched.txt").exists()


def test_an_engine_that_appears_during_the_wait_lets_the_pass_recover_core(tmp_path):
    """Docker Desktop started at sign-in brings its engine up about 12 s later; a pass that began
    first waits, then runs compose and launches Core as before."""
    engine_late = (
        "$script:probes = 0\n"
        "$script:live = 0\n"
        "function docker { param([Parameter(ValueFromRemainingArguments=$true)]$Arguments)\n"
        " if ($Arguments[0] -eq 'compose') { cmd /c exit 0; return }\n"
        " $script:probes++; if ($script:probes -le 2) { cmd /c exit 1 } else { cmd /c exit 0 } }\n"
        "function Invoke-RestMethod { param($Uri, $TimeoutSec, $MaximumRedirection)\n"
        " if ($Uri -like '*/health/live') { $script:live++; if ($script:live -le 1) { throw 'down' }\n"
        "  return [pscustomobject]@{status='ok'} }\n"
        " " + TAGS + " }\n"
        "function Get-NetTCPConnection { return $null }\n"
        "function Start-Process { throw 'UNEXPECTED_PROCESS_LAUNCH' }\n"
        "function Start-Sleep { param($Seconds, $Milliseconds) }\n"
    )
    result = run(tmp_path, engine_late, ["-EngineWaitSeconds", "20"])
    assert result.returncode == 0, result.stderr + result.stdout
    lines = log_lines(tmp_path)
    assert any(
        "Docker engine unavailable" in line and "waiting up to 20 s" in line for line in lines
    ), lines
    assert any("Docker engine available after" in line for line in lines), lines
    assert any("Core recovered and healthy" in line for line in lines), lines
    assert not any("compose:" in line for line in lines), lines
    assert (tmp_path / "launched.txt").read_text().split() == ["8000", "True"]


def test_the_default_wait_fits_the_tasks_ten_minute_limit():
    """40 s: the paper worst case of one pass (Ollama 30 s, compose 240 s, Core 90 s, two workers
    100 s each) plus the wait stays inside the task's PT10M execution limit (note section 2)."""
    script = (ROOT / "tools" / "ensure_core.ps1").read_text(encoding="utf-8")
    assert "[int]$EngineWaitSeconds = 40" in script
    assert "$CoreStartSeconds = 90" in script
