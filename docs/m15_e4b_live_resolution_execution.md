# M15-E4B Live Resolution-to-Execution Gate

## Status and claim boundary

M15-E4B is verified on CWRU as a native Neo4j/Fuseki mechanism gate. It
consumes one sealed E3 resolution commit through the E4 capability bridge,
materializes the matching namespaced workload before service startup, loads
both black-box backends, and executes all and only the four physical plans
attached to the two capability-complete semantic classes. It does not choose a
semantic winner, profile the current query, invoke an LLM or ontology service,
or claim a paper result.

## Lifecycle

The native-service wrapper creates the controlled E3 resolution artifact and a
run-local copy of the E4 bridge specification. Before either backend starts,
it reconstructs the resolution commit and source hashes, enumerates all six
semantic classes, checks capabilities, creates four physical candidates, and
writes a self-hashed preflight. The preflight records zero backend calls and
that no answer oracle was opened before the bridge was sealed.

The allocation then starts job-owned loopback Neo4j and Fuseki services and
loads the hash-bound fixture. The executor reopens and verifies the preflight
workload, checks both services, and runs the four candidates in the sealed
order. Each physical plan makes exactly one Neo4j and one Fuseki `execute`
call. A failed plan stops the gate; calls already in flight inside a parallel
plan remain charged, but no later plan starts and no call is retried.

## Semantic and physical boundary

The gate preserves the E4 cardinalities:

- six raw interpretations and six semantic equivalence classes;
- two executable classes and four explicitly unavailable aggregate classes;
- two physical strategies per executable class;
- four physical executions and eight backend calls in a successful run.

Every Neo4j artifact retains the hard exclusive upper bound
`occurred_on < 2026-09-01`. The portable bridge contains IDs, bindings,
capabilities, and hashes but no Cypher or SPARQL text. Unsupported window-total
and window-count meanings receive no physical candidate and never reach a
backend.

## Oracle and evidence boundary

Plan construction and execution order are sealed without answer rows. Oracles
are used only to validate the completed outputs. The independent auditor
recompiles the bridge from the run-local resolution and specification,
revalidates the generated workload and fixture, reconstructs every expected
plan/backend-artifact pair, recomputes exact answers, checks all eight
invocations and service cleanup, and compares the run tree before and after the
audit. A modified result row therefore fails reconstruction even if the stored
success marker was left unchanged.

The local tests use deterministic backend clients only. CWRU job `3792349`
executed exact clean commit `8056ee4` on `compt292` in 94 seconds. It completed
all four plans and eight backend calls, removed the allocation runtime, and
reported no cleanup error. The first read-only audit failed only because the
auditor expected a synthetic `loopback_only` field absent from the real
`NativeServicePlan` schema. Fix `aed12e3` now verifies `public_ports=false`, all
loopback HTTP endpoints, Fuseki's `--localhost` argument, and Neo4j's persisted
listen and advertised addresses. The v2 audit of the unchanged run passed all
152 checks with no run-tree mutation. The original failed audit is retained;
the experiment was not rerun. E4B remains `paper_result=false` because this is
mechanism acceptance, not semantic-quality, frontier, or performance evidence.

## Entry points

- `scripts/slurm/run_m15_native_resolution_execution_bridge.sbatch`
- `src/xgap/experiments/m15_live_resolution_execution_bridge.py`
- `src/xgap/experiments/m15_resolution_execution_bridge_evidence.py`

The CWRU run root is
`runs/cwru-m15-native-resolution-execution-bridge-<job-id>`. On success, the
auditor must write outside that immutable run tree:

```bash
PYTHONPATH="$PWD/src" \
"$HOME/venvs/xgap-core/bin/python" \
  -m xgap.experiments.m15_resolution_execution_bridge_evidence \
  --run-root "$XGAP_E4B_RUN" \
  --repo-root "$PWD" \
  --expected-commit "$XGAP_E4B_COMMIT" \
  --output "$XGAP_E4B_AUDIT"
```

Do not audit a failed run, overwrite an audit, or automatically resubmit a
failed external action.
