# XGAP

XGAP is a research prototype for cost-aware, agentic federated graph queries over
Neo4j and Apache Jena Fuseki. A bounded online controller selects information
requests, semantics-preserving plan transformations, and a final execution plan.

## Quick start

Python 3.10 or newer is required. The portable demo uses a small synthetic RDF
graph and makes no external model or network calls.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test-sparql,entity-answers,experiment-harness]'
python examples/unified_demo.py
```

## System

- `src/xgap/agent/`: bounded lookahead, semantic authority, and information actions.
- `src/xgap/semantic/`, `algebra/`, `pattern/`: typed query representation and semantics.
- `src/xgap/compilers/`, `planning/`: Cypher/SPARQL compilation and physical planning.
- `src/xgap/runtime/`, `backends/`, `tools/`: execution, backend clients, and metered tools.
- `src/xgap/experiments/`: reusable workload, measurement, and evaluation implementations.
- `tests/`, `datasets/`, `examples/`: regression tests, compact input fixtures, and demos.
- `scripts/`, `services/`: execution utilities and backend deployment support.
- `apps/xgap-ui/`: web interface; `xgap-local-ui` starts the Python local interface.

The primary API is `xgap.api.answer_unified`. The controlled API
`answer_unified_controlled` accepts an already specified initial semantic state.
Both use the same controller. See [architecture](docs/architecture.md),
[operator semantics](docs/operator_semantics.md), and [development](docs/development.md).

## Validation

```sh
python -m pip install -e '.[test-sparql,entity-answers,parquet,experiment-harness]'
make acceptance
```

Backend integration utilities require separately configured Neo4j/Fuseki services.
External model calls require an explicitly configured provider and credentials
supplied through environment variables. The local test suite uses temporary data
and service doubles; it does not submit cluster jobs.

## Scope

Candidate proposals do not certify user intent. Required validations and hard
query constraints remain independent of estimated execution cost. The controller
uses fixed-depth lookahead and does not claim global optimality. A structured
query-loss bound is not an answer-accuracy guarantee.

This repository contains implementation and reproducible test inputs. Development
reports, generated measurements, private deployment state, and historical run
archives are stored separately. Benchmark outcomes are not bundled with the code.
