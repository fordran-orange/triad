# Day 6 local synthesis context correction QA

Current decision: **PASS for the corrected source identified below**.
The original context-only PASS is preserved as history and explicitly overturned
for committed `fde92bb` by the subsequently discovered schema mismatch.
Independent reviewer `day6_qa_a`; builder root.
Date: 2026-09-19. Base: `bb1bb531b1951fcd3879aa7708eab686f46a9766`.

Reviewed `app/products/triad/development.py`, SHA-256
`3da702abf3dfb224cba85ccd62c17f3d53d7bfc903256d61dadbd2c9f40ac022`.

The diff changes only local synthesis context and verbosity guidance. Qwen
receives each original independent summary, inspector identity and candidate
titles. This constructs a new context without mutating persisted inspections
or candidates. Codex selection still receives full candidate fields and the
Qwen summary. Frontier inspection independence and original source grants are
unchanged; no strategy preference or decision authority is introduced.

The requested short summary/assumption fits the existing SUPPORT output schema
(`summary`, `assumptions`). LOCAL_QWEN/SUPPORT routing, local privacy requirement,
observe-only permissions, output caps and 120-second enforced deadline remain
unchanged. Synthesis still follows all three independent frontier inspections.

With `TRIAD_INTEGRATION=1`, existing local-privacy support routing and independent
read-call/journal tests passed: **2 passed**, 14.21 seconds. Ruff passed.

```text
python -m pytest tests/test_intelligence_routing.py::test_local_privacy_support_is_routed_to_qwen tests/test_day6_product_framework_qa.py::test_actual_readonly_call_completes_and_journals_executor -q
python -m ruff check app/products/triad/development.py
```

No live inference was run by QA. The smaller context is verified; resolution of
the observed live timeout requires the subsequent real retry. QA modified only
this report; no blocking finding remains in this bounded correction.

## Subsequent live failure and corrective QA — CHANGES_REQUIRED

The actual retry still failed at the enforced 120-second deadline:
`logs/day6-product-real-retry3.log` records `ProviderError: DeadlineExceeded`
in the LOCAL_QWEN SUPPORT call. The earlier context-only review did not exercise
the actual provider request-schema/decoder pair and therefore did not establish
live synthesis acceptance.

Corrective verdict against committed
`fde92bbf664b38e8e7239ab10c7aef6a706d3e89`: **CHANGES_REQUIRED**.
This supersedes the earlier PASS for actual SUPPORT compatibility while retaining
its test evidence. Canonical implementation reference supplied by the builder:
`0939e714-c378-43ca-8c5b-25ff639de728`.

**P1:** Development.call supplied the full AgentRunResult schema even for
SUPPORT. HttpProvider.execute sent that schema to Ollama's format constraint,
but decoded the returned JSON using a strict two-field SupportOutput
(`summary`, `assumptions`). A schema-following model therefore could not produce
an output accepted by the SUPPORT decoder. Merely requesting fewer words or
reducing generation budget did not resolve this incompatibility. The new
adapter-level negative control reproduces the old request format failing with
`MalformedOrUnsafeResponse`. The live deadline's sole cause is not inferred
from that structural finding.

## Corrected source and fresh independent QA — PASS

Final SHA-256 identities:

- `app/products/triad/development.py`:
  `bc6ea89430c4e0a5d65aa2b6fb73a92544e7701667c4b1aed7999b33b505ddc6`
- `tests/test_day6_product_framework_qa.py`:
  `b099163c9a47e67c3682f461af326481ac7d58c57df83d494c87561f5842ff7e`

The builder corrected SUPPORT to use Core.support's existing compact schema.
Other roles retain AgentRunResult. Qwen reasoning/generation allowance narrows
from 1,024 to 256; HttpProvider enforces this through num_predict=min(output,
reasoning), and the runtime validates the same ceiling. The broader WorkItem
output cap remains 2,048 and the existing static Qwen reasoning ceiling remains
1,024. No cap, deadline, permission or policy is raised.

The synthesis context now contains all three unchanged independent summaries
and inspector identities; candidate titles are omitted. Original records and
Codex's complete candidate input remain intact. A 35-word summary and empty
assumptions are requested without granting decision authority.

QA added a meaningful regression using the actual Development.call and
HttpProvider.execute with only HTTP transport mocked, against the disposable
integration fixture. It verifies exact request-format fields, actual
num_predict=256, think=false, read-only grants, successful strict decoding,
completed WorkItem/journal, and local usage. Its negative control demonstrates
that the previous full schema is rejected by the actual SUPPORT decoder.

Fresh result: **3 passed**, 19.30 seconds; Ruff passed. Evidence:
`logs/day6-product-synthesis-codec-qa.log`.

```text
python -m pytest tests/test_day6_product_framework_qa.py::test_qwen_support_uses_compact_adapter_schema_and_256_generation_cap tests/test_intelligence_routing.py::test_local_privacy_support_is_routed_to_qwen tests/test_day6_product_framework_qa.py::test_actual_readonly_call_completes_and_journals_executor -q
```

No live inference was performed by QA. This proves corrected adapter/schema
compatibility and narrowed generation authority; a real successful retry is
still required to close live acceptance. QA changed only this report and the
explicitly authorized independent regression test.
