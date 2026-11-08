# Local Ollama supervision

Triad uses the existing current-user Ollama installation at
`%LOCALAPPDATA%\Programs\Ollama\ollama.exe`. On this machine the model store is
`C:\AI\Models\Ollama`, configured in the user's `OLLAMA_MODELS` environment value.
The supervisor reads that persistent value before launching, preserving the store.
It never installs Ollama, downloads a model, relocates files, or runs inference.

`tools/ensure_core.ps1` checks Ollama even when Core's liveness endpoint is healthy.
`tools/ensure_ollama.ps1` checks the configured loopback HTTP endpoint and model;
if the port is unused, it starts the existing executable hidden and waits for
`/api/tags`. An occupied but unresponsive port, missing model, missing installation,
or conflicting host configuration fails visibly in its log without stopping any
process. An Ollama failure does not prevent Core recovery or remove diagnostics.

`tools/install_core_supervisor.ps1 -ValidateOnly` builds and displays the task
configuration without registering it. Normal installation registers a task for
the current interactive user, with a logon trigger, indefinite five-minute
checks, bounded failure retries and hidden PowerShell execution. It does not
store a password or run with elevated privileges. The task runs only while that
user is logged on; it is not a machine service. Register from the final deployed
checkout so the absolute action path is stable. Re-run installation only after
review and deployment if that checkout moves.

September 29 diagnosis: both Ollama executables and the login shortcut existed,
but there was no Ollama process or listener on 11434. Triad's URL and the user's
host setting agreed. The Qwen3 4B manifest and all five referenced blobs existed
with the expected sizes. The stopped process, rather than a moved model store,
explains the connection refusal; the cause of its earlier exit is not established.
One authorized hidden launch restored `/api/tags`, reporting `qwen3:4b` and manifest
digest `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.
No inference, Core restart, task installation, model change or trading occurred.

Builder tests exercise the actual PowerShell scripts with mocked network/process
seams, including healthy Core with failed Ollama, busy ports, missing models,
nonlocal/mismatched endpoints, hidden launch, and real Windows task construction
without registration. Independent QA remains required before deployment.

November 7 (`docs/CORE_DEPENDENCY_PORTS_AFTER_REBOOT.md`, section 10): every logged dependency
failure since September was Docker Desktop not running at sign-in. `tools/ensure_core.ps1` now
waits up to `-EngineWaitSeconds` (40) for the Docker engine before `docker compose up`, names a
Docker Desktop that is not running, and on a failed dependency start writes compose's last lines
and Windows' excluded TCP port ranges to `core-supervisor.log`, timestamped, so a reserved port
no longer reads like a missing engine. `tests/test_core_dependency_supervisor.py` drives those
seams the same way, with `docker`, `netsh`, the web and the clock mocked.
