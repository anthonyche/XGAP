# XGAP

XGAP is a cost-aware agentic federated graph-query system over heterogeneous
black-box graph engines.

Its core research question is how an agent should jointly choose
information-acquisition actions and federated execution actions for a
partially bound semantic graph program while minimizing end-to-end cost under
semantic and resource constraints.

## Current implementation

The repository contains:

- the audited path algebra, pattern lowering, and reference evaluator;
- bounded Cypher and SPARQL compilers;
- Neo4j and Fuseki native clients and capability profiles;
- reproducible LLM, ontology, planning, and experiment infrastructure from the
  original M0-M13 research track;
- typed Semantic Graph Programs with unresolved holes;
- a bounded goal/observation/tool loop and provenance-bearing memory;
- pluggable black-box backend tools;
- a typed SSH/Slurm experiment-control tool with exact-commit staging,
  allowlisted submission, observation, and artifact retrieval;
- a coordinator runtime for remote calls, ID alignment, explicit exchange,
  hash join, merge, failure propagation, and runtime metrics;
- per-backend fragment compilation through the existing M9 compilers.

The coordinator is verified locally with split backend fixtures. Live
Neo4j-plus-Fuseki validation is the remaining M15-B gate. Ontology and LLM use
are deliberately not required for that gate.

## Architecture

- [`docs/agentic_architecture.md`](docs/agentic_architecture.md)
- [`docs/m15_agentic_federated_core.md`](docs/m15_agentic_federated_core.md)
- [`docs/ui_remote_execution.md`](docs/ui_remote_execution.md)
- [`docs/status.md`](docs/status.md)

Mainline packages:

```text
xgap.semantic   typed semantic query/dataflow DAGs and holes
xgap.agent      goals, policies, observations, memory, bounded control
xgap.tools      typed tools and pluggable backend interfaces
xgap.runtime    federated fragments and coordinator execution
xgap.algebra    preserved path and focused-binding semantics
```

## Local verification

Python 3.10 or newer is required.

```bash
python -m pip install -e '.[test]'
python -m pytest
python examples/m15_goal_loop_demo.py
python examples/m15_federated_vertical_slice_demo.py
```

The complete acceptance workflow is:

```bash
./scripts/run_acceptance.sh
```

Live backend, LLM, CWRU, and large-dataset tests are separately gated. A clean
Git checkout does not contain the large GrailQA artifacts; the corresponding
tests skip until those versioned resources are installed.

## CWRU execution

Existing Slurm and loopback-only vLLM infrastructure is under `scripts/cwru/`
and `scripts/slurm/`. The remote-control path uses an implemented SSH/Slurm
tool and immutable artifacts. It never stores VPN, Duo, SSH-key, or model
credentials in the repository.

For the current M15 server gate and exact user handoff, see
[`docs/m15_remote_execution_loop.md`](docs/m15_remote_execution_loop.md).
