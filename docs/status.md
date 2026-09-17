# XGAP Current Status

T4 bounded joint system implementation is complete within its declared profile
(2026-09-17): [acceptance report](report/bounded_joint_system_20260917.md),
[Chapter 6 implementation map](implementation_chapter6.md).

|Item|Verified state|
|---|---|
|Current entry and legacy isolation|`xgap.api.answer`; three historical controllers moved, compatibility retained|
|NL candidates and authority|Bounded Cartesian/Top-K support, paid containment confirmation, scoped/full simulated user|
|Joint information/execution objective|Shared finite strong search, frozen estimates/fallback, feasible seed, one execution|
|Storage/memory|Streaming gzip, logical/stored hashes, raw replay support, budget-cause preservation|
|Correctness|88 targeted tests; real eight-node Neo4j+Fuseki gate; services closed|
|GitHub|Published on `codex/m13e4-grailqa-semantic-paper-protocol`; [review PR #1](https://github.com/anthonyche/XGAP/pull/1), not merged into main|
|Formal evaluation/Chapter 7|Await discussion; no new campaign launched|

This does not mean universal NL support or proven overall superiority. Current
bounds and two stale historical full-model replay tests are explicit in the report.
The real tiny gate returned four exact rows versus one ε-certified Performance row;
backend call counts were equal. Storage benefits are separately measured, not
presented as query speedup. T3 remains 47 sealed/65 unrun with its original version.

[Previous status](status_history_20260917_t3.md) is historical evidence only.
