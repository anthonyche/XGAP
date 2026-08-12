# M12-B Live Structured LLM And Runtime Ontology/Alignment Artifacts

## Goal

Replace M12-A's controlled model/alignment inputs with an optional runtime
path: bounded ontology context, an OpenAI-compatible structured provider,
deterministic grounding/alignment validation, frozen M12-A semantic
deviation, and the unchanged M11 planner.

## Required Scope

- generic OpenAI-compatible structured provider with DashScope Qwen and vLLM
  configuration;
- exactly one generation call and at most one schema-repair call;
- no committed credentials and no secret-bearing artifacts;
- bounded deterministic ontology/schema retrieval and prompt views;
- separate query-side anchors and candidate slot realizations;
- artifact-backed runtime alignment without gold answers, gold forms, or gold
  alignments;
- ontology-ID, slot-coverage, and backend-mapping validation;
- raw invocation, query-slot, grounding, validation, usage, and diagnostic
  artifacts;
- config-selected mock and live paths in the existing experiment runner;
- default offline tests plus an explicitly gated live Qwen smoke test.

## Forbidden Scope

Do not implement LoRA, model download/deployment, OWL/DL reasoning, native
query generation by the XGAP model, M12-C calibration/D0 collection, M12-D
baseline/ablation execution, benchmark loaders, logical optimization, or any
change to M11 physical search, GP confidence, threshold, or Nash semantics.

## Acceptance

- focused M12-B offline tests and fake-HTTP integration pass;
- all M12-A tests and mock experiment remain green;
- default pytest has no network requirement and live tests skip unless
  `XGAP_RUN_LIVE_LLM=1` with credentials;
- full pytest and `scripts/run_acceptance.sh` pass;
- completion docs distinguish runtime inputs from evaluation-only gold data
  and leave M12-C/D not started.
