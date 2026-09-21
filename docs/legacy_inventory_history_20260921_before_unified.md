# Current and historical code boundary

|Category|Location|Treatment|
|---|---|---|
|Current public entry|`src/xgap/api.py`|Use for new bounded joint-mode work|
|Current durable worker|`src/xgap/experiments/bounded_joint_worker.py`|Compressed evidence; no evaluation labels|
|T1 coordinate-only controller|`src/xgap/legacy/intent_policy.py`|Retained unchanged, old import shim|
|Early single/one-shot/practical dispatcher|`src/xgap/legacy/question.py`|Retained unchanged, old import shim|
|T2/T3 NL/finite-family dispatcher|`src/xgap/legacy/nl_strong_question.py`|Frozen methods remain reproducible, old import shim|
|Compiler/runtime/strong solver/estimator|`semantic`, `runtime`, `compilers`, `agent/strong_planning.py`, `planning`|Shared current substrate; not deleted as legacy|
|Old experiment workers/releases|`src/xgap/experiments`, `scripts`|Keep pinned schemas and old method behavior; do not route new runs implicitly|
|Old architecture/status/goal/harness|`*_history_20260917*.md`|Historical context; never current instructions|

`docs/decisions_history_20260917_t3.md` preserves the full previous decision index.
No frozen release, failed result, private artifact or original baseline was deleted
or rewritten. Reproduction must use the recorded code/profile version: compatibility
imports do not make a v1 model recording valid under a v2 semantic admission hash.

Current development data are bundled in `datasets/bounded_joint_toy_v1`.
External FinBench/GrailQA data, serving copies and credentials remain outside Git.
The experiment package still contains historical infrastructure because current
receipts depend on it; this is deliberate retention, not a claim of package-wide
cleanup or a stable public SDK.
