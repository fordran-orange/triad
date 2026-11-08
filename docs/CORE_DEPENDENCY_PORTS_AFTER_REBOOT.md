# Core's database dependencies after a reboot: measurements and a decision note

Date: 2026-11-04; decided 2026-11-07 (section 10). Status: **sections 1-9 are the measurement and the options as they stood for the decision; nothing in them was implemented when they were written.** No
change was made to Windows, Docker, the "Triad Core Supervisor" task, the compose file or any
script. Every command behind the numbers below was read-only (Appendix A). The one exception
that opens anything is a set of loopback bind probes that listened on a port for an instant and
closed it again; they changed no configuration.

Time zone: supervisor log times are local (CDT, UTC-5, until 2026-11-01; CST, UTC-6, after).
Docker's own logs are UTC and are converted here.

## 1. The short version

1. **The reboot problem that actually happens is Docker Desktop not running, not a reserved
   port.** The supervisor log holds 294 failed dependency starts between 2026-09-29 and
   2026-11-04. All 294 have the same cause: the Docker engine pipe does not exist because Docker
   Desktop has not been started. None of them is a bind, port or "address already in use"
   failure. Docker Desktop's "start when you sign in" is off. At the four boots whose launch
   time survives it was started 10 to 76 minutes after boot, with its dashboard window open, as
   if by hand; at the other two, about 10 and 17 hours after boot.
2. That cost **six boots with Core down for 10.7 minutes to 11.5 hours each, 24.4 hours in
   total** (section 3.2). Core does not start at all while Docker is down, because the
   supervisor runs `docker compose up` before it launches Core.
3. **The reserved port is real but rarer and not in the logs.** One incident is documented
   (`docs/MISSION8_PLATEAU_WALK_FORWARD.md`): after the 2026-10-18 reboot Windows had reserved
   TCP 57225-57824, which covers both Neo4j ports. The supervisor log cannot place it, and
   the three boots whose Docker log survives (10-28, 10-30, 11-02) forwarded 55432, 57474 and
   57687 without error, and the 10-14 and 10-27 starts also succeeded. By that count it hit once
   in six boots; the sample is too small to give a rate.
4. **Mechanism, measured today:** all three ports (55432, 57474, 57687) sit inside Windows'
   dynamic port range 49152-65535. Windows hands blocks of that range to its networking stack
   at boot, listed by `netsh` as "excluded ranges". A `bind()` inside such a block fails with
   Windows error 10013 (`AccessDenied`). I reproduced that failure on this machine for three
   current blocks. None of our three ports is inside a block right now.
5. **Recommendation:** do the Docker-start fix first, because it addresses every logged failure
   and needs no elevation or data change; then move the three published ports below 49152
   (proposed 15432, 17474, 17687, all verified free and bindable today), which removes the
   reserved-port risk for good. Reserving the ports with `netsh` is the lighter alternative,
   with an untested failure mode.
6. **Decisions needed from the operator** are listed in section 7. All three options are
   environment-level changes under `AGENTS.md` and stay unimplemented until decided.

## 2. How the dependencies start today

**Compose** (`docker-compose.yml`, project name `triad`):

| Service | Published (host side, loopback only) | Container port | Restart | Healthcheck |
| --- | --- | --- | --- | --- |
| postgres (timescale 2.25.2, pg17) | `127.0.0.1:${POSTGRES_PORT:-55432}` | 5432 | `unless-stopped` | `pg_isready`, 10 s, 12 retries, 30 s start period |
| neo4j 5.26 community | `127.0.0.1:${NEO4J_HTTP_PORT:-57474}` | 7474 | `unless-stopped` | `wget` on 7474, 10 s, 18 retries, 45 s start period |
| neo4j | `127.0.0.1:${NEO4J_BOLT_PORT:-57687}` | 7687 | (same service) | (same service) |

The three ports can be overridden through `.env`; the live `C:\Triad\.env` sets exactly the
defaults (`POSTGRES_PORT=55432`, `NEO4J_HTTP_PORT=57474`, `NEO4J_BOLT_PORT=57687`, and
`NEO4J_URI=bolt://127.0.0.1:57687`). Data lives in named volumes `triad_postgres_data`,
`triad_neo4j_data` and `triad_neo4j_logs`, not under any port.

**Who starts them:** only `tools/ensure_core.ps1` (and `tools/bootstrap.ps1`, once, at
installation). `ensure_core.ps1` first runs the Ollama check, then, if Core's `/health/live`
on port 8000 is not `ok`, it runs `docker compose up -d --wait --wait-timeout 240`, then
`start_backend.ps1 -CoreOnly`, then waits up to 90 s for Core to answer.

**Retry and wait behaviour:**

- Compose waits for container health (up to 240 s) **only after it has reached the Docker
  daemon**. If the daemon is not there it fails in a fraction of a second (294 failed
  attempts: minimum 0.36 s, average 0.98 s; one outlier of 97.6 s on 2026-10-18 19:37, cause
  unknown, its recorded message is the same pipe error).
- Nothing in the compose file or the script retries or waits for Docker to appear. The only
  retry is the next scheduled run.
- `restart: unless-stopped` brings both containers back by themselves when Docker starts. In
  the three Docker logs that survive, the container ports were forwarded 0.2 to 0.8 s after
  the engine came up, before the supervisor's next run. Once Docker is up, the supervisor's
  remaining job is only to launch Core (22 to 53 s after a run begins, section 3.2).

**The task** (`Get-ScheduledTask 'Triad Core Supervisor' | Export-ScheduledTask`):

- Triggers: a logon trigger for `RAGNAROK\fordr`, and a time trigger repeating every `PT5M`
  with no end (start boundary 2026-09-30T18:22:07).
- Action: `C:\Triad\.venv\Scripts\pythonw.exe "C:\Triad\tools\run_core_supervisor.py"`, working
  directory `C:\Triad`. That launches `ensure_core.ps1`, then `ensure_product_worker.py` for
  Triad and for Aegis (100 s timeout each).
- Principal `fordr`, interactive token, least privilege. It runs only while that user is
  signed in.
- Settings: `MultipleInstancesPolicy IgnoreNew`, `StartWhenAvailable true`,
  `ExecutionTimeLimit PT10M`, `RestartOnFailure` 3 times at `PT1M`, runs on battery.
- The log shows no 1-minute retries. Attempts follow the logon run and then the 5-minute
  cadence (on 11-02: 13:30:17, 13:32:12, 13:37:11, 13:42:11, and so on).
- Paper worst case for one pass today: Ollama 30 s + compose 240 s + Core 90 s + 2 x 100 s
  workers = 560 s, against the 600 s limit. Any wait added to the script must fit in the
  remaining 40 s in that worst case, or the limit must be raised.

**Where the failure is recorded.** `core-supervisor.log` gets only
`Core recovery failed: docker compose dependency startup failed (1)`. Compose's `stdout` goes
to `Out-Null`; its `stderr` lands in `logs/supervisor-launcher.log`, which has **no
timestamps**. A "Docker not running" failure and a "port blocked" failure therefore read
identically in the log that anyone looks at.

## 3. Measurements

### 3.1 The supervisor log

`C:\Triad\logs\core-supervisor.log`: 9,018 lines, 2026-09-29T13:40:05 to 2026-11-04T10:52:09.
8,392 are `Core healthy on port 8000`. The other 626 fall into 19 outage episodes:

- 13 episodes were Core-only recoveries with Docker up (7 to 78 s to recover; no failures).
- **6 episodes contain all 294 `docker compose dependency startup failed (1)` lines.**

`logs/supervisor-launcher.log` (371 lines, un-timestamped) holds compose's stderr for those
runs. It has 294 pipe errors, matching the 294 failures one for one, and nothing else on a
failure:

```
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine; check if the path is correct and if the daemon is running: open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
```

Searching that file for `address already in use`, `bind`, `not available`, `excluded` and
`forbidden by its access permissions` returns no match. The same search across all retained
Docker Desktop logs (`%LOCALAPPDATA%\Docker\log`, 2026-10-26 onward) returns no port-bind
error either (the word "bind" appears there only in internal IPC lines).

The 2026-11-02 sequence (the one the originating note refers to), quoted:

```
2026-11-02T13:30:17.6078509-06:00 Core unavailable; ensuring database dependencies
2026-11-02T13:30:18.1569054-06:00 Core recovery failed: docker compose dependency startup failed (1)
   ... same pair every 5 minutes, 8 failures in all, last at 14:02:12 ...
2026-11-02T14:07:11.7145778-06:00 Core unavailable; ensuring database dependencies
2026-11-02T14:07:40.4978590-06:00 Core recovered and healthy on port 8000
```

### 3.2 Every reboot in the log's window

Boots come from the System event log (Kernel-General event 12, 2026-09-28 onward; the log only
holds boots from 2026-10-14). Docker times come from `com.docker.backend.exe` and the Docker
GUI logs where they survive; the older ones were rotated away. Fast Startup is on
(`HiberbootEnabled=1`), so a "shutdown" followed by power-on is a hybrid boot; each row below
has its own event 12.

| Boot (OS start) | First supervisor run | Docker Desktop launched | Engine running | Core healthy | Boot to Core | Port or bind error |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-10-14 00:24:50 (third of three Windows Update restarts: 00:22:36, 00:24:04, 00:24:50) | 06:15:08 | between 17:32:11 and 17:37:12 (no Docker log kept) | not kept | 17:42:10 | 17 h 17 m | none logged |
| 2026-10-18 19:13:07 | 19:13:59 | between 05:47:12 and 05:52:11 on 10-19 (not kept) | not kept | 10-19 05:52:33 | 10 h 39 m | none logged; see 3.3 |
| 2026-10-27 06:43:47 | 06:45:04 | 06:53:26 (GUI log; backend log rotated) | not kept | 06:58:10 | 14 m 23 s | none logged |
| 2026-10-28 20:21:11 | 20:22:08 | 20:31:22 | 20:31:36 | 20:32:50 | 11 m 39 s | none |
| 2026-10-30 06:58:06 | 06:59:00 | 08:14:07 | 08:14:19 | 08:17:47 | 1 h 19 m 41 s | none |
| 2026-11-02 13:29:19 | 13:30:17 | 14:03:44 | 14:03:56 | 14:07:40 | 38 m 21 s | none |

Outage as the supervisor saw it, first failed run to recovery, with the number of Docker-pipe
failures: 10-14 687.0 min (137 failures); 10-18/19 638.6 min (128); 10-27 13.1 min (3); 10-28
10.7 min (2); 10-30 78.8 min (16); 11-02 37.4 min (8). **Total 1,465.6 minutes, 24.4 hours.**
On 10-14 the first run came 5 h 50 m after boot (nobody signed in until then); that stretch
is not counted. The 10-14 recovery also logged `Core did not become healthy within 30
seconds` at 17:37:59, the old 30 s Core wait that `ensure_core.ps1` now sets to 90 s.

What the three complete Docker logs show once Docker was started:

- Backend start to engine running: 13.4 s (10-28), 12.0 s (10-30), 11.95 s (11-02).
- Container ports forwarded 0.2-0.8 s later, for example on 11-02:

```
[2026-11-02T20:03:55.832546300Z] ... sending desktop state:EngineRunningState
[2026-11-02T20:03:56.224566700Z] ... exposer.Add(f0b8775f..., /triad-neo4j-1, [TCP 127.0.0.1:57474 -> 172.18.0.2:7474 TCP 127.0.0.1:57687 -> 172.18.0.2:7687])
[2026-11-02T20:03:56.544314700Z] ... exposer.Add(8ed73d04..., /triad-postgres-1, [TCP 127.0.0.1:55432 -> 172.18.0.3:5432])
```

- Engine running to Core healthy: 74 s (10-28), 3 m 28 s (10-30), 3 m 44 s (11-02). That lag is
  the wait for the next 5-minute tick plus a 29-35 s Core start.

The Docker GUI log for each launch gives `reason: 'open-tray'` with the dashboard opened
(10-26, 10-27, 10-28, 10-30, 11-02). That is consistent with launching Docker Desktop by hand;
I did not observe who launched it.

### 3.3 The one documented port incident

`docs/MISSION8_PLATEAU_WALK_FORWARD.md` (lines 126-129): "since the 2026-10-18 reboot Windows
reserved TCP 57225-57824, which covers Neo4j's host ports 57474 and 57687, so Docker published
neither. The operator restored them with an elevated `net stop winnat`, recreating the
container and `net start winnat`. The durable fix (Neo4j ports below the reserved range) is a
Core configuration decision left open."

What I can and cannot say about it:

- It belongs to the 10-18 boot, whose supervisor log is 128 pipe failures followed by a
  recovery. **The log does not show a port failure at any point.** At 10-19 05:52:11 the
  dependency start succeeded in 21.7 s with both containers healthy, so the Neo4j ports were
  bindable at that moment, either because the reservation was not yet in place or because the
  operator had already applied the fix.
- So "after a reboot" is the Mission 8 session's inference. The same reservation may be made
  whenever the Windows networking stack rebuilds its virtual networks (for example when
  Docker or WSL restarts), not only at OS start. I could not test this.
- Reservations of 600 ports (57225-57824) match today's total: the current dynamic blocks add
  up to 600 ports too (3.4). Two snapshots only.

### 3.4 Windows now (2026-11-04, 45.5 hours after the 11-02 boot)

```
netsh int ipv4 show excludedportrange protocol=tcp
      5357        5357
     50000       50059     *
     56805       56904
     64116       64215
     64415       64514
     64515       64614
     64615       64714
     64715       64814
* - Administered port exclusions.

netsh int ipv4 show dynamicport tcp
Start Port      : 49152
Number of Ports : 16384
```

- The dynamic range is 49152-65535 (the Windows default). **55432, 57474 and 57687 are all
  inside it**, so any of them can be inside a block after some boot.
- **None is inside an excluded block today.** The nearest block below 57474 is 56805-56904 (570
  ports under 57474, 1,373 above 55432), and the next above 57687 is 64116 (6,429 away).
- Every block in the dynamic range is 100 ports, or 100-port blocks side by side (64415-64814
  is four): six blocks, 600 ports in all.
  The only blocks outside the range are 5357 (one port) and the administered 50000-50059
  (marked `*`; it is the only administered entry, and `HKLM\...\Tcpip\Parameters\ReservedPorts`
  does not exist).
- `netsh` does not report which component owns a block. `hns`, `winnat` and `vmcompute` are
  all running, and `Get-NetNat` returns nothing; the owner is inferred, not measured.
- Docker Desktop 4.97.0, engine 29.9.2 on the WSL2 backend (kernel 6.6.87.2-microsoft-standard-WSL2),
  no `.wslconfig`. Listeners on all three ports are `com.docker.backend` (PID 14856): the
  Windows-side forwarder, not a container, makes the host `bind()`.

**Bind probes** (a .NET `TcpListener` on `127.0.0.1`, started and stopped at once, as the
signed-in user):

| Port | What it sits in | Result |
| --- | --- | --- |
| 56850 | dynamic block 56805-56904 | `SocketException 10013 (AccessDenied)` |
| 64150 | dynamic block 64116-64215 | `10013 (AccessDenied)` |
| 64500 | dynamic block 64415-64814 | `10013 (AccessDenied)` |
| 50030 | **administered** block 50000-50059 | **bind OK** |
| 56950 | dynamic range, not excluded | bind OK |
| 57474 | in use by Docker now | `10048 (AddressAlreadyInUse)` (control) |
| 15432, 17474, 17687 | below the dynamic range | all bind OK; nothing is listening on them |

So a block owned by the networking stack blocks every ordinary `bind()`, which is exactly the
failure Docker's forwarder would hit; an administered exclusion does not block binds, only
the stack's own allocation. (That is the property Option B relies on.)

### 3.5 Docker Desktop settings

- `%APPDATA%\Docker\settings-store.json`: `"AutoStart": false`, `"EngineTypeWindows": "wsl2"`
  (the Linux engine runs in the WSL2 VM; `docker info` confirms).
- `HKCU\...\Run` has a `Docker Desktop` entry pointing at `Docker Desktop.exe`, but its
  `StartupApproved\Run` flag reads `01 00 00 00 ...`, and Docker did not start at sign-in on
  any of the six boots (the first supervisor run found no engine every time). I did not
  establish why the Run entry has no effect.
- Both containers have been up 45 hours without a restart. `docker volume ls` shows
  `triad_postgres_data`, `triad_neo4j_data`, `triad_neo4j_logs`, `triad_baseline_graph_restore`
  and one unnamed volume.

## 4. Mechanism

1. Windows keeps a dynamic (ephemeral) port range, here 49152-65535. Outbound connections take
   their local ports from it, and the Hyper-V stack carves "excluded" blocks out of it for its
   own use (WSL2 and Docker Desktop run on that stack). The blocks are chosen at the time and
   are different on different boots; the two snapshots I have (10-19 and today) both sit in
   56805-64814.
2. A `bind()` to a port in such a block fails with error 10013 even for an ordinary process
   (probe results above). Docker's forwarder, `com.docker.backend`, is an ordinary process, so
   a container whose published port falls in a block cannot start.
3. If the dependency start hit this, compose would exit non-zero and the supervisor would log
   the same `docker compose dependency startup failed (1)` every 5 minutes, indefinitely, with
   the real reason in an un-timestamped file. Nothing escalates it.
4. Ports in the dynamic range carry a second, unmeasured risk: an outbound connection may
   already hold a given local port when Docker tries to publish it (error 10048). No such
   error appears in any retained log.
5. Rough exposure, an estimate and not a measurement: if the six 100-port blocks landed uniformly
   over 16,384 ports, each port has a 600/16,384 = 3.7 % chance per boot, about 10 % that at
   least one of the three is hit. One hit in six boots does not contradict that, but two
   snapshots both in the upper part of the range also do not prove uniformity.

## 5. Options

### Option A: move the published ports below 49152 (proposed 15432, 17474, 17687)

Ports below 49152 are never in the dynamic range, so neither the excluded blocks nor outbound
connections can touch them. The only remaining excluded port below the range on this machine
is 5357. 15432, 17474 and 17687 are not excluded, bind today, and have no listener.

Every place the numbers appear (`grep -rn '57474\|57687\|55432'`; the 4 hits in
`tests/fixtures/aegis_engine_golden.json` are inside equity floats, not ports):

| Where | Lines | Change |
| --- | --- | --- |
| `C:\Triad\.env` (live, untracked) | `POSTGRES_PORT`, `NEO4J_URI`, `NEO4J_HTTP_PORT`, `NEO4J_BOLT_PORT` | 4 values; **this alone moves the ports**, for compose and for Core |
| `.env.example` | 6, 9, 10, 11 | 4 values |
| `docker-compose.yml` | 12, 32, 33 | the three `:-` defaults, so a missing variable does not silently restore the old ports |
| `app/trading_core/settings.py` | 18, 22 | the two defaults (`postgres_port`, `neo4j_uri`); **Core code, shared contract** |
| `docs/DAY1_SETUP.md` | 63-65 | the setup table |
| `docs/DAY2_VERIFICATION.md`, `CORE_STATE_AUDIT.md` | 76, 78; 91, 96, 308 | dated evidence; leave as history |
| `docs/MISSION8_PLATEAU_WALK_FORWARD.md` | 127 | history, leave |

No test asserts a port value. Everything that connects (`store.py`, `brain.py`,
`health_check.py`, `persistence_probe.py`, `init_graph.py`) reads `settings`, so it follows
`.env`. There are six worktrees and none has its own `.env`. Anything outside the repository
that points at the old ports (a database client, a browser bookmark to Neo4j Browser on 57474)
is unknown to me and would need the new number.

Procedure and cost:

- The published port is only a mapping; the data volumes are named and are not touched. The
  container-internal ports (5432, 7474, 7687) do not change.
- `docker compose up -d` sees the changed port mapping and **recreates both containers once**
  (Postgres holds canonical data, Neo4j a rebuildable projection per `CORE_STATE_AUDIT.md`).
  A clean `docker compose stop` before it is the careful way. Core must be restarted
  (`ensure_core.ps1 -Restart`) to read the new `.env`. Expect one to two minutes in which Core's
  databases are unavailable; I have not measured a recreate, only
  the 21-53 s of a normal start on healthy containers.
- Needs no elevation. Under `AGENTS.md` it is an environment-level change and it touches
  `app/trading_core/`, so it needs the operator's decision, the relevant Core tests, and, because
  it recreates the container that holds canonical Postgres, independent QA of the procedure.
- Rollback is the same edit in reverse. Failure mode: another program claims one of the new
  ports (unlikely; they are free now).

### Option B: reserve the current ports with `netsh` (one elevated command, no repo change)

```
netsh int ipv4 add excludedportrange protocol=tcp startport=55432 numberofports=1
netsh int ipv4 add excludedportrange protocol=tcp startport=57474 numberofports=1
netsh int ipv4 add excludedportrange protocol=tcp startport=57687 numberofports=1
```

(Elevated. Not run. Undo with `delete excludedportrange` and the same arguments.)

- Why it can work: an administered block is persistent, keeps the stack from carving those
  ports into a dynamic block, and keeps them out of outbound allocation. It does not block
  `bind()` (probe on 50030, section 3.4), so Docker can still publish them.
- **Failure mode, from the incident itself:** the command is refused if a dynamic block
  already covers the port, which is the state on 10-18. Then the fix is the operator's
  `net stop winnat`, the add, `net start winnat`, with the container recreation they already
  did. I believe it is also refused while a program is listening on the port, which would
  mean running it with the containers stopped or right after boot before Docker starts; **I
  could not test either, as it needs elevation and a change.**
- Persistence across a reboot is documented behaviour but not observed here; the existing
  `50000-50059` entry has been there for at least this uptime, and I do not know when it was
  made.
- Cost: no file, container or Core change, no data risk. Its weakness is that it protects
  only these three ports and must be redone if a port is ever changed, and the reservation
  lives in Windows rather than in the repository, where the next session cannot see it.

### Option C: Docker Desktop at sign-in, and a supervisor that waits for the engine

This option does nothing for a blocked port; it removes the failure seen at every boot.

- **C1, the setting:** in Docker Desktop, Settings > General > "Start Docker Desktop when you
  sign in". It is a per-user Docker setting (`AutoStart` in `settings-store.json`); no
  elevation and no repository change. Docker's engine takes about 12 s after its own start.
- **C2, `tools/ensure_core.ps1` (and an optional change to the task):**
  - Before `docker compose up`, poll the engine (`docker info`, or the
    `\\.\pipe\dockerDesktopLinuxEngine` pipe) for up to about 60 s, then continue as today.
    The wait must fit the `PT10M` limit; the paper worst case is 560 s (section 2), so either
    cap the wait near 40 s or raise `ExecutionTimeLimit` (a task change).
  - Log compose's stderr, timestamped, in `core-supervisor.log`, and on a failure also append
    `netsh int ipv4 show excludedportrange protocol=tcp`. That makes the next reserved-port
    incident measurable instead of inferred, and tells a missing Docker from a blocked port.
  - `IgnoreNew` already stops overlapping runs, so a long wait cannot pile up.
- **C3, variant:** the supervisor starts `Docker Desktop.exe` itself when the pipe is missing,
  as `ensure_ollama.ps1` does for Ollama. It also covers Docker being quit mid-session, but
  it overrides a deliberate quit, may open the dashboard window (all five observed launches
  did), and does more than a wait. I would not start there.
- Effect, from the measured delays: Docker would start at sign-in, the containers come back
  by themselves about 12 s after its engine starts, and with the wait Core would follow within
  roughly the 22-53 s a Core start takes. That is an estimate; I could not test a sign-in.
  Today the same step takes 11 minutes to 11.5 hours. Without the wait (C1 alone) Core
  recovers on the next 5-minute tick after the engine is up.
- Open: whether starting Docker earlier changes where the dynamic blocks land. I have no
  measurement; if the blocks are made when the virtual network is created, an earlier start
  moves the timing, not the placement.
- Cost and risk: a settings toggle plus roughly 20 lines of PowerShell; reversible; no data
  involved. It is startup and supervisor change, so `AGENTS.md` makes it the operator's
  decision; the script is shared supervision code, so it should be tested the way
  `docs/OLLAMA_SUPERVISION.md` says the existing supervisor scripts are (the real PowerShell
  with mocked network and process seams).

### Option D: change nothing

The recovery is the operator's elevated `net stop winnat`, recreate, `net start winnat`
after noticing that Core stays down. At the observed pace (one hit in six boots, six boots in
five weeks) that is about once in five weeks, from a sample too small to trust. The
Docker-not-running outage stays at the 24.4 hours in five weeks seen above.

## 6. Recommendation

1. **Do C (C1 + C2, not C3) first.** It addresses 294 of 294 logged failures and all six
   multi-minute to multi-hour outages, needs no elevation, touches no data, and its logging
   change turns the reserved-port question from inference into measurement.
2. **Then do A.** It ends the reserved-port risk for all three ports, and the ephemeral
   collision risk, without relying on timing or elevation. Its cost is real but one-off: four
   lines in the live `.env`, four in `.env.example`, five defaults, one doc, a two-container
   recreate and a Core restart, under the Core tests and independent QA that `AGENTS.md`
   asks for. Move Postgres too, so one change removes the whole class.
3. **Choose B instead of A** only if the operator wants no repository or container change. It
   is a legitimate stopgap but I could not verify its two failure modes.
4. Keep the operator's winnat procedure as the documented manual fallback until A is done.

## 7. What the operator must decide

1. **Docker start (Option C):** approve C1 (turn on "Start Docker Desktop when you sign in")
   and C2 (bounded wait and timestamped failure logging in `ensure_core.ps1`)? Choose between
   a 40 s wait inside the current 10-minute limit and a raised limit. Is C3 wanted?
2. **Ports:** A, B or D? If A, approve the numbers 15432 / 17474 / 17687 (or name others
   below 49152) and a short window to recreate the containers and restart Core, and say
   whether external clients use the old numbers.
3. **Measurement:** if C2 is approved, I propose that the failure-time `excludedportrange`
   snapshot stay in the supervisor log permanently.
4. **Who and when:** the work is Core shared-infrastructure under `AGENTS.md`; say whether it
   waits for the operator or runs in an assigned session.

## 8. What was not measured

- The Windows side was measured once, today. I could not see the excluded-range table at any
  earlier boot; for 10-19 I have only the Mission 8 note.
- Docker's wording for a blocked port was not reproduced, and neither was
  `netsh ... add excludedportrange`, which needs elevation and a change.
- No recreate of the containers was timed.
- The Docker logs before 2026-10-26 are gone, so boots on 10-14 and 10-18 have no Docker times
  and no Docker-side port record.
- Who launched Docker Desktop each time is inferred (AutoStart off; dashboard opened).
- The Triad and Aegis worker supervisor logs were not examined; they were outside this brief.

## Appendix A. Read-only commands used

`Get-ScheduledTask 'Triad Core Supervisor' | Export-ScheduledTask`;
`netsh int ipv4 show excludedportrange protocol=tcp`;
`netsh int ipv4 show dynamicport tcp|udp`;
`Get-WinEvent` on the System log (event 12, 1074, 6005, 6006, 6008, 41);
`Get-CimInstance Win32_OperatingSystem`; `Get-NetTCPConnection -State Listen`;
`Get-Service winnat,hns,vmcompute,WslService`; `Get-NetNat`;
`reg query` for `Tcpip\Parameters\ReservedPorts` and `HiberbootEnabled`;
`docker ps`, `docker volume ls`, `docker version`, `docker info`, `docker compose config` (output
filtered to port lines); reads of `core-supervisor.log`, `supervisor-launcher.log`, the Docker
Desktop logs under `%LOCALAPPDATA%\Docker\log\host`, `settings-store.json` and `.env` (the port
variables only); `Get-ItemProperty` on the `Run` and `StartupApproved\Run` keys; `grep` over the
repository; and the bind probes in section 3.4. Nothing was stopped, restarted, installed or
edited.

## 9. Update 2026-11-07: a seventh boot and a third port-block snapshot

Read-only, the same sources as above. Nothing has been decided or implemented since section 7.

**The boot.** Windows started at 08:50:31 (Kernel-General event 12). The supervisor's first run
at 08:55:18 failed on the Docker pipe, as did the runs at 08:57:11 and 09:02:40 (three
`docker compose dependency startup failed (1)` lines, the launcher log holding the same pipe
error). Docker Desktop was started between 09:02:43 and 09:07:32; the 09:07:32 run brought Core
back at 09:08:19. Boot to Core 17 m 48 s; outage as the supervisor saw it 13.0 minutes. Docker's
`AutoStart` is still `false`. The seven-boot totals are now 297 pipe failures and 1,478.6 minutes
(24.6 hours) of Core down, every one of them Docker not running, none a port.

**The blocks.** `netsh int ipv4 show excludedportrange protocol=tcp` at 14:50, six hours after
the boot:

```
      5357        5357
     49152       49251
     49409       49508
     50000       50059     *
     64952       65051
     65052       65151
     65254       65353
     65391       65490
```

Six dynamic blocks of 100 ports again (600 in all), this time two at the bottom of the range
and four at the top. 55432, 57474 and 57687 are in none of them; all three are listened on by
`com.docker.backend`. The three snapshots (57225-57824 on 10-19; 56805-64814 on 11-04;
49152-49508 and 64952-65490 today) now span the whole dynamic range, so section 4's uniform
estimate (about 3.7 % per port per boot, about 10 % that one of the three is hit) is the right
order of magnitude and the "upper part" remark in section 3.3 no longer holds. One hit in seven
boots. Nothing in this update changes the recommendation in section 6.

## 10. Decision 2026-11-07 and what was built

The operator's word, 2026-11-07 evening, after the four questions of section 7 were put to him
with the recommendation of section 6: **"Approve C then A"**. Read as the recommendation says:
C1 and C2 with the 40 s wait inside the current task limit, no C3, the excluded-range snapshot
permanent; then A with the proposed numbers 15432 / 17474 / 17687. He named no external client of
the old numbers; the question stands in 10.4.

### 10.1 C1, applied on the machine the same evening (no repository change)

What Docker Desktop's own toggle writes, written directly, because this session cannot click in
Docker's window and its CLI (`docker desktop`, 4.97.0) has no command for the setting:

| Where | Before | After |
| --- | --- | --- |
| `%APPDATA%\Docker\settings-store.json`, key `AutoStart` | `false` | `true` (the one key replaced in the 308-byte file; a copy of the file as it was is in the session's scratchpad) |
| `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run`, value `Docker Desktop` | `01 00 00 00 00 00 00 00 00 00 00 00` | `02 00 00 00 00 00 00 00 00 00 00 00` |
| `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, value `Docker Desktop` | `C:\Program Files\Docker\Docker\Docker Desktop.exe` | unchanged |

Why both: Docker's forum reports that the toggle adds and removes the `Run` value, and that
Windows' `StartupApproved` flag beside it is what Task Manager's Startup tab toggles. The `Run`
value was already present, so Docker's own flag alone could not have been what kept it from
starting; the `StartupApproved` value was the only entry under that key on this machine, so
Docker Desktop was the only startup item carrying an explicit flag. `02` is the value every
source gives for "enabled" and `03` for "disabled"; none documents `01`, and the informal readings
(an odd first byte, or anything but `02`) both call it disabled, which matches seven boots
without a start. No `-Autostart` argument was added to the `Run` value: no Docker source
documents one.

Untested until the next sign-in, which is the only test there is. The supervisor log's logon run
tells: with C2 in place it should read `Docker engine unavailable; waiting up to 40 s for Docker
Desktop`, then `Docker engine available after N s`, then `Core recovered and healthy` within about
a minute of sign-in. If Docker Desktop's General settings show the box unticked after its next
start, tick it there: Docker writes `settings-store.json` from its own memory on a settings save
(it wrote the file at 09:07:04 today, a second before its process started), and this edit was
made while it was running. Undo: `AutoStart` back to `false` and the flag back to its old bytes.

### 10.2 C2, `tools/ensure_core.ps1` (this branch)

- A new parameter `-EngineWaitSeconds` (default 40, range 0-300). Before `docker compose up`,
  `docker version --format '{{.Server.Version}}'` probes the engine by the road compose takes;
  while it fails the pass waits, probing every 2 s, and logs once
  `Docker engine unavailable; waiting up to 40 s for Docker Desktop`, then
  `Docker engine available after N s` when it appears. If it does not, the pass ends with
  `Core recovery failed: Docker engine unavailable after 40 s; Docker Desktop is not running`
  and compose is not run. 40 s keeps the paper worst case of one pass (section 2: 560 s) inside
  the task's unchanged `PT10M` limit; the task was not touched.
- Compose's output is captured (the error preference set to `Continue` around the native call,
  since under `Stop` a redirected stderr line is a terminating error in PowerShell 5.1). On a
  non-zero exit its last 20 non-empty lines go to `core-supervisor.log` as `compose: ...`, each
  timestamped, followed by one line `excluded TCP port ranges: ...` holding the rows of
  `netsh int ipv4 show excludedportrange protocol=tcp` joined with ` | `. That is the permanent
  snapshot of decision 3: the next reserved-port incident is measured where it happens, and a
  blocked port no longer reads like a missing engine. Compose's stderr no longer passes through
  to the untimestamped `supervisor-launcher.log`; on a successful start nothing of it is kept.
- Tests, `tests/test_core_dependency_supervisor.py` (core scope; the real PowerShell with
  `docker`, `netsh`, the web, the process and the clock mocked; nothing starts):
  a missing engine is waited for, named, and compose and Core's launcher are not reached;
  a failed compose leaves its stderr and the excluded-port table in the log, timestamped;
  an engine that appears during the wait lets the pass run compose and recover Core as before;
  the default wait is 40 s and Core's 90 s wait is unchanged. The existing supervisor tests
  (`test_ollama_supervisor.py`, `test_quiet_supervisor.py`) hold.
- `docs/OLLAMA_SUPERVISION.md` gains a paragraph pointing here.

### 10.3 A, the repository side (this branch; harmless to merge before the live move)

| File | Change |
| --- | --- |
| `app/trading_core/settings.py` | `postgres_port` default 55432 → 15432; `neo4j_uri` default `bolt://127.0.0.1:57687` → `bolt://127.0.0.1:17687`; a two-line comment naming this note |
| `docker-compose.yml` | the three `:-` defaults: 55432 → 15432, 57474 → 17474, 57687 → 17687 |
| `.env.example` | `POSTGRES_PORT`, `NEO4J_URI`, `NEO4J_HTTP_PORT`, `NEO4J_BOLT_PORT` |
| `docs/DAY1_SETUP.md` | the three rows of the service table |

The live `C:\Triad\.env` still carries the old numbers and overrides every default, so merging
this changes nothing that runs until 10.4 is carried out. Dated evidence (`DAY2_VERIFICATION.md`,
`CORE_STATE_AUDIT.md`, `MISSION8_PLATEAU_WALK_FORWARD.md`) keeps the old numbers as history.
`tests/test_aegis_settings.py` writes `POSTGRES_PORT=55432` into its own temporary env file and
reads it back; it tests the file, not the default, and is unchanged. The browser walk's
Core-change lists already name `settings.py` (Mission 14's list and the worker settings view's);
`docker-compose.yml` and `tools/` are outside `app/trading_core`, so the lists hold.

### 10.4 A, the live move (procedure; nothing executed yet)

Core shared infrastructure that recreates the container holding canonical Postgres: under
`AGENTS.md` it runs only after the independent QA of this procedure (10.5) and on the operator's
word. Everything below is reversible; the data volumes are named and are not touched by a port
change. Expect one to two minutes without Core and its databases, and a few more without the
product workers.

0. **Preconditions.** Core healthy; `docker ps` shows both containers healthy; nothing listens on
   15432, 17474 or 17687 (`Get-NetTCPConnection -State Listen -LocalPort 15432,17474,17687` is
   empty; all three are below the dynamic range, so no excluded block can cover them). Start
   right after a supervisor tick (a `Core healthy` line; the ticks fall about every five minutes
   on the clock pattern of the log) so that the task does not run its own pass mid-move. If it
   does, it runs `docker compose up` with the same new `.env` and launches Core: the same steps,
   not a conflict.
1. **Postgres dump, belt and braces.** From Git Bash, binary-safe:
   `D=C:/Triad/data/temp/ports-move-$(date -u +%Y%m%dT%H%M%SZ); mkdir -p "$D";`
   `docker exec triad-postgres-1 sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$D/postgres.dump"`
   then `sha256sum` and size, and `docker exec -i triad-postgres-1 pg_restore --list < "$D/postgres.dump" | head`
   to prove the dump reads. The container's own environment supplies the names; nothing from
   `.env` is printed. Neo4j is a rebuildable projection (`CORE_STATE_AUDIT.md`) and its volume is
   equally untouched; no dump.
2. **The live `.env`**, four lines by name, nothing else read or printed:
   `sed -i -E 's/^POSTGRES_PORT=.*/POSTGRES_PORT=15432/; s#^NEO4J_URI=.*#NEO4J_URI=bolt://127.0.0.1:17687#; s/^NEO4J_HTTP_PORT=.*/NEO4J_HTTP_PORT=17474/; s/^NEO4J_BOLT_PORT=.*/NEO4J_BOLT_PORT=17687/' C:/Triad/.env`
   and confirm with `grep -c` of the four new lines. No copy of `.env` is made anywhere; the
   rollback is the same four edits with the old numbers.
3. **Recreate the containers** from `C:\Triad`: `docker compose stop`, then
   `docker compose up -d --wait --wait-timeout 240`. Compose reads the project's `.env`, sees the
   changed port mappings and recreates both containers against the existing volumes
   (`triad_postgres_data`, `triad_neo4j_data`, `triad_neo4j_logs`). Expect `Recreated` and both
   `Healthy`.
4. **Core**: `tools\ensure_core.ps1 -Restart` (its pass: Ollama, the engine, compose as a no-op,
   `start_backend.ps1 -CoreOnly`, which stops the `uvicorn platform_host.api:app` listener on 8000
   and relaunches it on `.venv`, then the 90 s health wait). Core reads the new `.env` at start.
5. **Workers**: both read `.env` once at start (Aegis through `AegisSettings`, Triad through
   `Settings`) and hold the old port otherwise. Relaunch each detached, as the 8102 restarts of
   2026-11-07 were done (a `Win32_Process` `Create` of
   `tools\start_product.ps1 -Product triad`, then `-Product aegis`, each of which stops the
   worker's listener and relaunches it on its own environment). The product-development lease
   keeps the supervisor from launching a second copy meanwhile.
6. **Verify**: `/health/live` on 8000, 8101 and 8102; `tools/health_check.py` on `.venv`
   (authenticated Postgres and Neo4j through `Settings`, so through the new ports; JSON without
   credentials); `/aegis/api/status` 200 with the same work-item count as before (47 on
   2026-11-07) and the providers route 200; `docker ps --format '{{.Names}} {{.Ports}}'` showing
   `127.0.0.1:15432->5432`, `127.0.0.1:17474->7474`, `127.0.0.1:17687->7687`;
   `Get-NetTCPConnection -State Listen` on the three new ports owned by `com.docker.backend` and
   nothing on the three old ones; the supervisor's next tick `Core healthy`; Neo4j Browser at
   `http://127.0.0.1:17474`.
7. **Record** the move here (times, the `Recreated` lines, the verification) and in the
   operator's memory; anything outside the repository on the old numbers (a database client, a
   Neo4j Browser bookmark) is the operator's to repoint, and none was named.

Rollback at any step: the four `.env` lines back to 55432 / 57687 / 57474 / 57687, `docker compose
up -d --wait`, step 4, step 5. The dump of step 1 is the last resort for a volume that is lost,
which a port change does not cause: `docker exec -i triad-postgres-1 pg_restore -U <user> -d
<db> --clean < postgres.dump`.

### 10.5 Governance

Core shared infrastructure under `AGENTS.md`: the supervisor script and Core's settings defaults
are shared runtime, and 10.4 recreates the container that holds retained canonical data. So:
the Core tests run on this branch before the merge; an independent, read-only QA of C2's change
and of the procedure in 10.4 runs before the merge and before 10.4 is executed; the merge, the
push and the live move are each the operator's word. `tools\verify.ps1` at the merge, in
`C:\Triad` on `main`. Results are recorded in 10.6 as they come.
