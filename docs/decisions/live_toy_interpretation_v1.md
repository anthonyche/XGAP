# T2-C: one-call live Interpretation on the existing tiny graph

2026-09-11, scope frozen before implementation on local bea9321.

Connect an OpenAI-compatible semantic-program provider to run_question. Reuse
the existing transport, exact local pinned chat-token guard, semantic validator,
frozen resolution bundle and planner/executor. Keep Qwen3-32B BF16 and the
12288-token context; at most one generation per question and no repair/retry.
Provider response, usage availability, bounded request and version provenance
must survive errors and the existing offline recording/replay boundary.

Allowed changes: new llm provider and small language prompt/schema; minimal
usage/provenance plumbing in Interpretation and its journal; optional provider
injection into the existing five-question tiny harness; focused tests, tiny
launch assets and status documentation. No algebra/compiler/runtime changes,
new benchmark population, gold changes, catalog build or general replay system.

First connectivity input remains the five B01–B05 development questions and
explicit caller constraints. A language reference may describe operator syntax;
no expected answer, gold program, target query or physical plan enters inference.
These manually structured requirements and tiny development questions do not
establish unrestricted NL accuracy. Compare answers only after execution and
retain every question's terminal status, including skipped after infrastructure
failure. Template/controlled transport runs are interface evidence only.

Acceptance: one-call payload/token guard; missing key or preflight failure makes
zero calls; transport/invalid response retains observed calls, reported tokens
and safe raw response; unavailable usage is explicit; no relaxed constraints or
authoritative entity candidates bypass the existing validator. Save/replay
responses and failures with zero new model calls. Keep the existing tiny slice,
run focused tests then one broad offline acceptance. A real model response and
real tiny dual-backend execution are separately live-gated and cannot be claimed
from transport stubs. Server runs before development acceptance are restricted
to model health and tiny connectivity, never large datasets.

The pinned serving interface is documented in vLLM 0.11.1:
[JSON schema output](https://docs.vllm.ai/en/v0.11.1/features/structured_outputs/)
and [Qwen3 non-thinking mode](https://docs.vllm.ai/en/v0.11.1/features/reasoning_outputs/).
Actual server compatibility still requires the small live check.
