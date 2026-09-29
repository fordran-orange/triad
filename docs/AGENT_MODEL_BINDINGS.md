# Reviewed static-agent model bindings

A provider's observed model can change while its configured static grant remains
immutable. `AgentModelBinding` is a Core-owned append-only overlay. It never updates
`core.agent_instances.definition`, and the existing SQL trigger remains intact.
The previous-model field and definition digest refer to that original raw grant,
not the resource or engineering overlays returned by `Agents.get`.

The trusted Core host prepares `ModelBindingRequest` with these fields:

- `agent_id`, `provider`, `transport`, `previous_model`, `model`
- `base_definition_digest`: `fingerprint(raw_definition)`
- `test_proof`, `work_proof`: the currently selected canonical Core REAL proof IDs
- `capability_versions`: exactly three current independently approved versions for
  `structured_output`, `isolated_text_read`, and `document_analysis`, for the new
  model and the same provider/transport. Each requires only `read` permission.

The full request must be independently reviewed, including canonical successful
run/usage evidence. Include `binding_marker(request)` in BOTH the Core
ImplementationRun evidence and its independent QARun evidence. Do not invent a
PASS or reuse a verdict that covers only the source implementation.

After that exact request has independent passing QA, the trusted host may publish:

```python
from trading_core.intelligence.agents import Agents
from trading_core.intelligence.model_binding import ModelBindingRequest, binding_marker
from trading_core.intelligence.records import Records

request = ModelBindingRequest.model_validate(reviewed_request)
marker = binding_marker(request)  # Must already be bound in build AND QA evidence.
identifier = Agents(Records()).bind_model(
    request, implementation_id, reviewed_commit
)
```

No HTTP or model-facing publication endpoint exists. Scoped product records cannot
publish or forge the binding kind. Publication requires active, idle Core-owned
static identity, current control permission, exact independent QA and canonical
runtime/capability evidence. Existing failed repair/cycle records are preserved;
publication does not retry product work.

`Agents.get` resolves only the latest Core binding before the existing engineering
and resource overlays. Valid bindings change only the model. Every read rechecks
QA, the immutable baseline, current policy, selected proof IDs and successful
canonical run/usage, and the exact current read capability versions and their QA.
If those no longer match, effective execution is disabled; an older binding is
not silently revived. The original grant remains unchanged. A new selected proof
or capability version requires a new explicitly reviewed binding. Existing policy,
kill, scope, independent-review and routing checks continue to apply.

This is a model identity repair, not permission to use unverified write tools,
paid APIs, private cross-product data, or a new provider framework.
