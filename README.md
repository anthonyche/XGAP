# XGAP

XGAP is a research prototype for agentic federated graph queries. One online
controller jointly chooses metered information acquisition, bounded physical
transformations and one final execution over Neo4j/Fuseki. It uses fixed-depth
lookahead and replans after each actual observation. It does not enumerate a
complete horizon-wide policy or claim global optimality.

## Start here

- [Current architecture](docs/architecture.md) and [Chapter 6 implementation map](docs/implementation_chapter6.md)
- [Unified planning contract](docs/decisions/unified_lookahead_migration_20260921.md)
- [Verified readiness and remaining limits](docs/report/unified_prerelease_20260921.md)
- [Status](docs/status.md), [goal](docs/goal.md), [next steps](docs/roadmap.md)
- [Operator semantics](docs/operator_semantics.md), [decision index](docs/decisions.md)
- [Historical entry points and results](docs/legacy_inventory.md)

## Current entry

`xgap.api.answer_unified` accepts an NL request, a compact proposal provider,
frozen finite candidate domains and a private simulated-user authority. The user
tool confirms scope and supplies requested binding validations; the model and
catalog never certify user intent. `answer_unified_controlled` starts from an
explicitly published initial state for separate controlled experiments.

`Lambda` names validations that may remain unresolved; `epsilon` bounds the
implemented structured-query discrepancy over the confirmed finite family.
They configure the same algorithm. Mandatory validation is independent of zero
discrepancy or candidate uniqueness. Neither setting promises a speed advantage
or bounds output answer error.

A completion recipe reserves required validations and final execution resources.
Optional probes and rewrites cannot consume an already certified route to
completion. Missing resource bounds remain unknown; this is a conditional
protection, not a promise to answer every feasible query.

## Portable development slice

From this checkout, Python 3.10+:

```bash
python -m pip install -e '.[test-sparql]'
PYTHONPATH=src python examples/unified_demo.py
PYTHONPATH=src python examples/unified_demo.py --sequential
```

The demo uses an explicit English template grammar and an eight-entity synthetic
RDF graph. It makes zero LLM/network calls. Real-model, native and RDF engineering
gates are separately recorded in the readiness report; they are not comparative
benchmark results.

New batch method IDs are `xgap-unified-lookahead` and `xgap-unified-sequential`.
The shared `scripts/run_bounded_joint_batch.py` accepts the separately versioned
`xgap-unified-lookahead-batch-v1` manifest. Inputs/configuration/code are pinned,
answers and captures are compressed losslessly, scoring follows sealing, and
resume never repeats attempted cells. Credentials remain environment references.

The historical `answer(..., mode=...)`, strong-policy solver and frozen results
remain reproducible under their original IDs. They are not the current algorithm.
Formal campaigns and old automations remain paused; the current milestone stops
before a new full experiment release.
