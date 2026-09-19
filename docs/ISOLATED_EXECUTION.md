# Offline tool execution boundary

`triad.day5a.isolation.OfflineSandbox` is a host-only execution primitive. It runs
commands on explicitly supplied text snapshots in disposable Linux containers
using the existing Docker Desktop engine. It does not mount the repository,
Windows home, credential stores, Docker socket, or any other host directory.

The runtime image is the official Python image, pinned by manifest digest in
`isolation.py`. Setup requires that exact image to be pulled; execution uses
`--pull=never` and fails if Docker or the image is unavailable. There is no host
execution fallback. The toolbox currently contains Python and the base shell
utilities, not the vendor CLIs or a complete development toolchain.

## Enforcement

- Network namespace has no external interface (`--network=none`). No ports,
  additional devices, privileged mode, or host namespaces are exposed.
- Root filesystem is read-only; tools run as UID 10001, with all capabilities
  dropped, no-new-privileges, and Docker's default seccomp policy.
- A separate UID 10002 seeds supplied files. Inputs and directories are read-only
  to tools, except explicitly granted writable directories.
- Workspace and temporary storage are bounded tmpfs (64 MiB and 16 MiB).
  Container limits are 256 MiB RAM with no additional swap, one CPU, 64 processes,
  and 128 open descriptors. Per-command deadlines cannot exceed 120 seconds.
- The supervisor exits after 180 seconds, bounding container lifetime even if
  the host application crashes. Normal completion, failure, revocation, timeout,
  and cancellation force-remove the container and all descendants.
- No host environment or provider login state is passed into the container.
  Known secret material in command arguments and input content is rejected.
- Returned text files are proposals only. Export rejects symlinks and special
  files, uses no-follow directory-relative reads, and limits count and bytes.
  No output is ever automatically written to a host path.

The trusted host must construct snapshots and write grants from the immutable
WorkItem, and pass its live policy/control-epoch guard to `run`. Model output
must never choose grants. Returned output and changes are untrusted, including
any printed assertions or command claims; they require normal schema, path,
budget, and independent-review validation. Concurrent tools can race their own
outputs; this is not an atomic or tamper-proof provenance system.

## Integration status

Codex now has a separate **read-only review** integration in `codex_executor.py`.
Its app server owns the existing ChatGPT login on the host. An explicit remote
environment points to a version-matched exec-server in the offline container.
A random-path, single-connection loopback WebSocket relay carries protocol messages
over Docker stdio; the container still has no network interface except loopback.
No provider login files, tokens, or cookies are copied or parsed.

Triad mediates the executor protocol before forwarding it. Native shell reads are
parsed and rebuilt as `cat -- APPROVED_FILE`; arbitrary shell syntax, mutations,
stdin writes and unknown methods are denied. Environment overrides are stripped.
File content reads must name a supplied file. WorkItem tool-call limits and live
control-epoch guards apply. The host records source hashes, observed commands,
rewritten argument vectors, actual model and token usage. Model-generated evidence
is not treated as proof. App-server integrations (MCP, plugins, hooks, browser,
multi-agent, image generation and web search) are disabled for these runs.

This is not general CLI development support: writing, arbitrary commands and Git
operations remain unavailable. Claude and Grok still fail closed. The reasoning
and authentication app-server process remains trusted host infrastructure; the
container encloses execution, not that host process. A compromised host app-server
is therefore outside this boundary's guarantees. The remote protocol is experimental
and pinned to `0.155.0-alpha.2.6`; different versions do not enable this route.

Setup: run `.venv\Scripts\python tools/build_codex_executor.py`. It verifies the
pinned official npm archive's SHA-512 integrity, copies only the Linux executable,
and builds the dedicated image. `tools/check_codex_executor.py` checks the remote
connection without invoking a model. Real provider checks use Triad's normal
WorkItem, journal, usage and policy routes. No API fallback is enabled.

Native Codex input includes tool definitions and repeated conversation context.
The runtime reserves an additional 48,000 input tokens within the existing daily
ceiling. Known usage is retained even when result validation fails. A reservation
does not increase the daily ceiling; insufficient budget blocks the run.

Docker Desktop and its Linux VM/kernel are trusted infrastructure. This boundary
does not defend against a hostile Windows operator, compromised Docker daemon,
or a container runtime/kernel vulnerability.

## Verification

Run `.venv\Scripts\python -m pytest tests/test_isolation.py -q` from `C:\Triad`.
Tests run real containers when the pinned image is available; otherwise those
tests are explicitly skipped. These are sandbox checks, not provider ONLINE or
Day 5A acceptance evidence.

Controls follow Docker's [container run documentation](https://docs.docker.com/engine/containers/run/)
and [none network driver documentation](https://docs.docker.com/engine/network/drivers/none/).


## Claude and Grok file integrations

`native_agents.py` connects Claude's native tool loop through a dedicated MCP
server and Grok's native Read/Edit tools through ACP filesystem callbacks.
`bounded_tools.py` validates each call and invokes fixed `cat` or Python file-write
operations inside `OfflineSandbox`; models cannot supply executable code, Docker
options, host paths, environment variables or credentials. Each call gets a fresh
container seeded from the approved in-memory snapshot. Exported proposals carry
forward within the run but never apply themselves to the host repository.

Only exact file grants are copied for reviews. Proposal roles start with no host
files and may stage text only under current governed improvement directories.
The output must exactly match exported changes. Writes are limited to 12,000 bytes
per file, three staged files, 48,000 aggregate bytes, and at most the WorkItem's
bounded tool-call count (capped at 30). Existing downstream line/output limits and
independent review still apply. Unknown protocol operations and catalog changes
are denied. Both harnesses use empty temporary working directories, not `C:\Triad`.

Claude `2.1.276` has no built-in tools and only Triad's ephemeral MCP server.
Grok `1.0.34 (3736acbc8658)` uses an explicit ACP agent profile and verifies the
resulting tool list; a command-line tool restriction alone is insufficient. Grok
configuration inventory must contain no enabled unrelated hooks/plugins/MCP/LSP.
Both CLIs retain their own subscription credentials on the trusted host. A
compromised vendor executable, Windows account or Docker daemon is outside this
boundary. This is isolation of model-requested file operations, not isolation of
the entire vendor inference process.

Run `.venv\Scripts\python tools/check_native_agents.py` for real protocol and
offline read/proposal checks without inference. Unit/protocol tests are in
`tests/test_native_agents.py`; routing/accounting tests use a disposable database.
Neither creates successful provider proofs or changes budgets. Native inference
continues to reserve the existing extra 48,000 input tokens and fails closed when
the daily allowance is insufficient.

Protocol references: [Claude CLI](https://code.claude.com/docs/en/cli-reference),
[Grok ACP](https://docs.x.ai/build/cli/headless-scripting), and the
[official Grok source](https://github.com/xai-org/grok-build/tree/a28ee2b2063426e8816e380ccea528b9de95e5da).
