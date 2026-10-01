# INT-4: prepared path meaning to typed entity answers

This development milestone addresses R-E/E1's execution-side answer boundary.
It does not evaluate model quality or execute the frozen GrailQA150 cohort.
The prior model0/5 and FinBench3-query/6-plan exact results remain unchanged.

## Implemented behavior

`run_resource_entity_answers` takes the existing BoundSemanticExecutionTool.
The program itself must explicitly contain a single complete Traverse followed
by Project with one `answer:path_node` expression. An explicit first, last or
one-based node position is accepted; missing or out-of-range positions fail
before database access, even for an empty graph. There is no default answer
position, inference from variable names or read of an evaluation reference.

The adapter checks the frozen resource encoding and logical snapshot across
replicas. It reuses the existing program/metadata leakage check and ordinary
run_agentic_semantic_query → binding → polynomial placement → backend scheduler.
It does not add an optimizer or bypass constraints. Snapshot agreement is a
deployment declaration, not proof of the loaded endpoint's factual contents.

Successful projected IRI strings must round-trip through the declared namespace
and canonical identity encoding. They are explicitly converted to typed RDF
URI terms and normalized with the existing AnswerProjection. Backend failures,
missing rows, invalid terms and overflow cannot become successful empty answers.
A complete successful empty result is retained. The full agent trace, including
failed tool observations and acquisition/execution costs, remains in the result.
Answer conversion is separately timed and included in adapter end-to-end time.
No execution-time or NL-quality guarantee is added to the P1 model certificate.

## Verification scope

Independent tiny RDF tests exercise compiled SPARQL through RDFLib and the
ordinary agent/P1 execution path. They distinguish explicit first/last/interior
positions, incoming edges, deduplicated paths and empty results, plus admission,
identity, overflow and backend-failure risks. All **16 checks passed in 0.66s**
on their first run; process wall time was 1.149s. Source/test/contract hashes were
unchanged across the run. The fixture is independent and hand-authored; graph
execution uses an in-process RDFLib engine through a FusekiClient transport
override, not running Neo4j or Fuseki servers. The only output perturbation is
an explicitly marked duplicate-row injection after a real tiny agent run, to
check that the adapter's row limit applies before answer deduplication.

Command: `PYTHONPATH=src:tests /tmp/xgap-directed-tests.qU2YfW/venv/bin/python -m pytest -vv tests/test_resource_entity_answers.py`.
Raw log and receipt: `/Users/anthonyche/xgap-data/int4-resource-entity-answers-20260911/`.
[Machine evidence](../../experiments/artifacts/resource_entity_answers_20260911.json)
records the exact source hashes, command, scope and limitations.
No existing successful gate, native service, model request, catalog build or
large benchmark is rerun for this local adapter.

## Remaining boundary and current remote work

The legacy PlannerCandidate format still has no inferred answer-projection
contract, and the frozen150 runner remains semantic-only. This milestone does
not infer the missing projection or report GrailQA EM/F1. A new inference-side
contract and independently prepared real facts remain required before that
evaluation; preserve every150/48 ID and all earlier failure records.

The user has now staged08e4b3b on Pioneer, received a successful zero-model-call
token-preflight summary, and submitted H100 job3804210. The raw preflight checks,
scheduler allocation/state and new responses have not been received. This is
submission evidence, not a new model-quality result. Do not repeat submission.
See the [submission receipt](../../experiments/artifacts/cwru_toy_model_v2_submission_20260911.json).

Contract: [resource_entity_answers_v1](../decisions/resource_entity_answers_v1.md).
