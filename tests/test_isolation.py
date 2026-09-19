"""Real offline container boundary checks; never provider ONLINE evidence."""

import threading

import pytest
from triad.day5a.isolation import OfflineSandbox, safe_path


@pytest.mark.parametrize(
    "path", ["../secret", "/etc/passwd", "C:/Triad", ".env", "a/.git/x", "a//b", "a\\b", "."]
)
def test_reject_unsafe_paths(path):
    with pytest.raises(ValueError):
        safe_path(path)


@pytest.fixture
def sandbox():
    if not OfflineSandbox.available():
        pytest.skip("Pinned offline Docker runtime unavailable")
    return OfflineSandbox()


def run_python(sandbox, code, files=None, **kwargs):
    return sandbox.run(["python", "-I", "-c", code], files or {}, **kwargs)


def test_real_os_boundary(sandbox):
    result = run_python(
        sandbox,
        r"""
import os, pathlib, socket
assert os.getuid() == 10001
assert pathlib.Path('README.md').read_text() == '# Approved snapshot'
assert not pathlib.Path('/var/run/docker.sock').exists()
assert not pathlib.Path('/host').exists()
assert not pathlib.Path('/mnt/c').exists()
assert not any('TOKEN' in k or 'PASSWORD' in k or 'API_KEY' in k for k in os.environ)
assert 'NoNewPrivs:\t1' in pathlib.Path('/proc/self/status').read_text()
assert 'CapEff:\t0000000000000000' in pathlib.Path('/proc/self/status').read_text()
for path in ['README.md', '/workspace/new-file', '/etc/probe']:
    try: pathlib.Path(path).write_text('escape')
    except OSError: pass
    else: raise AssertionError('write unexpectedly allowed: '+path)
try: os.setuid(0)
except PermissionError: pass
else: raise AssertionError('became root')
for address in [('1.1.1.1',443), ('127.0.0.1',8000)]:
    try: socket.create_connection(address, timeout=1)
    except OSError: pass
    else: raise AssertionError('network escape')
print('BOUNDARY_PASS')
""",
        {"README.md": "# Approved snapshot"},
    )
    assert result.exit_code == 0, result.stderr
    assert result.stdout.strip() == "BOUNDARY_PASS"
    assert result.files == {}


def test_changes_are_only_returned_as_proposals(sandbox):
    result = run_python(
        sandbox,
        "from pathlib import Path; Path('docs/new.md').write_text('new'); "
        "Path('docs/old.md').unlink()",
        {"README.md": "protected", "docs/old.md": "old"},
        writable=("docs",),
    )
    assert result.exit_code == 0, result.stderr
    assert result.files == {"docs/new.md": "new"}
    assert result.deleted == ("docs/old.md",)


def test_symlink_output_rejected(sandbox):
    with pytest.raises(RuntimeError, match="runtime operation failed"):
        run_python(sandbox, "import os; os.symlink('/etc/passwd','docs/link')", writable=("docs",))


def test_timeout_kills_container_and_descendants(sandbox):
    result = run_python(
        sandbox,
        "import subprocess,time; subprocess.Popen(['sleep','90']); time.sleep(90)",
        timeout=1,
    )
    assert result.status == "TIMEOUT"
    assert result.files == {}


def test_output_flood_is_bounded(sandbox):
    result = run_python(sandbox, "print('x'*300000)")
    assert result.status == "OUTPUT_LIMIT"
    assert len(result.stdout) <= 131072


def test_guard_revocation_cleans_up(sandbox):
    calls = 0

    def guard():
        nonlocal calls
        calls += 1
        if calls >= 5:
            raise PermissionError("work revoked")

    with pytest.raises(PermissionError, match="work revoked"):
        run_python(sandbox, "import time; time.sleep(90)", guard=guard)


def test_cancel_cleans_up(sandbox):
    timer = threading.Timer(2, sandbox.cancel)
    timer.start()
    try:
        with pytest.raises(PermissionError, match="cancelled"):
            run_python(sandbox, "import time; time.sleep(90)")
    finally:
        timer.cancel()


def test_known_secrets_rejected_before_launch(monkeypatch):
    monkeypatch.setenv("TRIAD_TEST_TOKEN", "boundary-test-secret-value")
    with pytest.raises(PermissionError, match="Secret material"):
        run_python(OfflineSandbox(), "print('boundary-test-secret-value')")


def test_no_containers_left_after_checks(sandbox):
    assert sandbox._docker(["ps", "-aq", "--filter", "label=triad.offline-tools=1"]) == ""
