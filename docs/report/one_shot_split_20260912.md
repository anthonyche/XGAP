# Necessary split-source NL-only integration

The new gate uses four Neo4j-only profiles and three Fuseki-only relationships
plus identity stubs. Its request contains original NL and reusable source schemas,
with no prepared operator IDs, hard-constraint structure, output contract or gold
program. The unchanged v2 training model is embedded in an offline serving
deployment with independently frozen source statistics; it is not refitted.

Four new checks passed in 0.42s; the zero-call preflight passed. This verifies
deployment identity and both required-source compiled strategies, not NL success.
The catalog initially rejected duplicate case-normalized aliases before publication;
unique aliases corrected that local preparation failure. A secure runpy launcher
initially lacked the scripts import path and failed before any harness or service
action. Both local failures are retained in the evidence receipt.

## First real attempt: 20a96e7

One qwen3.8-27b call used 2,161 input and 801 output tokens. It returned a candidate
with correct relations/profiles source assignments and a reachability/age/join
shape, but put a list-valued condition inside the path source descriptor. It also
used a name property there instead of an unresolved identity hole, even though
relations has no names. Local typed admission rejected the unknown source field;
there was no grounding, planning or query execution. Backend query calls = 0,
final executions = 0, training/fit = 0. This is an Interpretation failure, not a
catalog or database failure. The unmodified response remains replayable.

Both stores loaded successfully and were stopped (Neo4j12778, Fuseki12813;
independent process inspection empty). All454 before/after input fingerprints
match. Parent model `33badbbe8e8ecea1e69c5318902a809219a96d5d4a775e36fd06750070eee177`
is unchanged; serving deployment is
`a2c547d33531e0043a496e98b421232e083badfb8988d1c3bdce1f47dac7872a`.
Core online interpretation-to-terminal cost was4367.119ms; setup7120.324ms and
load192.114ms are separate. No runtime prediction was made.

[Machine-readable first-attempt evidence](../../experiments/artifacts/one_shot_split_first_attempt_20260912.json).
Full artifacts: `/Users/anthonyche/xgap-data/one-shot-split-native-20260912-20a96e7`.

## Directed correction and next boundary

The new explicit `nl-only-identity-v1` prompt appendix supplies generic legal
identity-hole/node-descriptor syntax. It contains no query-specific identity,
threshold, answer or operator program. The earlier prompt/provider and schemas
are unchanged. Two new checks pass in0.22s: unchanged failure replay and separately
authored identity syntax through admission/grounding. These are local checks,
not a repaired model result. A new actual request under this version remains the
next gate; do not rerun the four accepted checks or collect more estimator labels.
Any later success on this same question is development-exposed and does not erase
the first failure or constitute independent model-accuracy evidence.
