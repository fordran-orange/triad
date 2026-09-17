# Agent Control Plane

Humans configure intent; agents receive immutable bounded assignments. Day 2's operational policy is `app/triad/control.py` (version day2-v1), enforced by `gateway.py` and `orchestrator.py`. `work.py` defines runtime contracts, `store.py` persists decisions and transitions, and PostgreSQL triggers protect assignment authority.

The retained Day 1 `policy.py` compiler and schemas document human intent compilation. Its legacy examples are not a second runtime authority or a promise that every example tool is implemented. Day 2 runs use registry.json, WorkItem validation and the operational ControlPlane; the only exposed broker tools are documented in PERMISSIONS.md.

Policy decisions answer who may work, which paths/tools are granted, what compute is bounded, whether review is required and whether money/trading/governance is affected. Unknown capabilities/tools, excessive authority, invalid paths and review bypasses are denied. Governance requires human authorization and remains blocked; live/money effects are denied outright.

Agents can submit an ElevationRequest but no Day 2 code approves it. API mutations require the operator token and there is no policy-mutation endpoint. A model cannot choose a privileged principal, see credentials, edit registry/control code, assign itself more compute or mark its own reviewed work complete.

This local broker protects against untrusted model outputs within trusted host adapters. It is not an OS sandbox for hostile plugins or a production multi-user authentication system. See PERMISSIONS.md, WORK_ITEMS.md and REVIEW_SYSTEM.md for concrete checks and limitations.
