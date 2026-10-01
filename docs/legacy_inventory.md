# Current and historical code boundary

|Category|Location|Treatment|
|---|---|---|
|Current public entry|`api.answer_unified`, `answer_unified_controlled`|New unified profile|
|Current controller/domain|`agent/unified_lookahead.py`, `unified_family.py`, `unified_contract.py`|Fixed-depth online decisions and completion protection|
|Current actions|`agent/unified_information.py`, `runtime/unified_physical.py`|Selected information calls and single checked rewrites|
|Current method/config boundary|`experiments/unified_contract.py`|New method IDs, no legacy configuration mixing|
|Shared durable worker/driver|`bounded_joint_worker.py`, `run_bounded_joint_batch.py`|Versioned routing preserves both generations; filename is not algorithm identity|
|Historical bounded joint entry|`api.answer(..., mode=...)`, `answer_controlled`|Original full-policy route; frozen old IDs only|
|Historical strong solver|`agent/strong_planning.py`, `agent/intent_strong.py`|Retained for old results and shared types; not new online controller|
|Early controllers|`legacy/intent_policy.py`, `legacy/question.py`, `legacy/nl_strong_question.py`|Frozen code and import shims|
|Audited compiler/runtime/estimator|`semantic`, `runtime`, `compilers`, `planning`, `algebra`|Shared active substrate; not disposable legacy|
|Old releases/reports|`experiments`, `scripts`, `docs/report`|Original schemas/evidence preserved, never relabelled|
|Superseded current documents|`*_history_20260921_before_unified.md`|Verbatim historical context; not active directions|

Paths above are relative to `src/xgap/` except the batch script and documentation.
Current development facts are `datasets/bounded_joint_toy_v1`; large datasets,
private users, credentials and run packages remain outside Git. Compatibility
imports do not make recordings valid under a different source/config hash.
Historical examples are labelled; use `examples/unified_demo.py` for the new API.
