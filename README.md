# XGAP

XGAP is a research prototype for bounded, cost-aware agentic federated graph
queries. The current implementation searches finite AND/OR strong policies over
metered clarification and estimated federated execution. It executes one selected
plan across Neo4j/Fuseki. It does not claim arbitrary natural-language support or
global optimality.

## Start here

- [Current architecture](docs/architecture.md) and [Chapter 6 implementation map](docs/implementation_chapter6.md)
- [Current engineering contract](docs/decisions/bounded_joint_system_v1.md)
- [Status and verified limits](docs/status.md), [goal](docs/goal.md), [roadmap](docs/roadmap.md)
- [Semantic contract](docs/operator_semantics.md), [decision index](docs/decisions.md)
- [Historical entry points and results](docs/legacy_inventory.md)

## Current entry

`xgap.api.answer` accepts an NL request, a compact proposal provider, a frozen
finite scope policy and a private simulated-user authority. It constructs the
candidate scope, pays for authoritative containment confirmation, plans with one
shared cost objective, follows the observed clarification branch and executes once.

EXACT requires zero residual structured-intent discrepancy. PERFORMANCE accepts
a user-declared epsilon certificate over the same confirmed candidate set. It may
save clarification or execute a cheaper certified query. No speedup is guaranteed;
zero epsilon uses the Exact terminal condition. See the implementation map for the
meaning and limitations of the distance and cost estimates.

## Portable development slice

From this checkout, Python 3.10+:

```bash
python -m pip install -e '.[test-sparql]'
PYTHONPATH=src python examples/bounded_joint_demo.py --mode exact
PYTHONPATH=src python examples/bounded_joint_demo.py --mode performance --epsilon 1/2
PYTHONPATH=src:tests:scripts python -m pytest tests/test_bounded_joint.py tests/test_evidence_store.py -q
```

The demo uses a declared English template grammar and bundled synthetic eight-node
RDF data. It makes zero LLM/network calls; it validates interfaces and semantics,
not NL model quality or benchmark performance. Model use employs the existing
`OpenAICompatibleCompactInterpretationProvider`. The durable current worker is
`python -m xgap.experiments.bounded_joint_worker --help`; it takes hash-pinned
request, deployment, public scope and private-user files. Its caller owns backend
services and study limits. Credentials are environment references only.

Large response/answer evidence is streamed to lossless gzip with both stored and
logical hashes. Source transfer bytes remain uncompressed logical bytes. Replay
validates identities and retains old raw-record compatibility.

Formal experiment design follows acceptance; frozen earlier results are preserved
and are not silently relabelled as results from this version.
