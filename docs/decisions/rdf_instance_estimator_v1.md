# RDF instance projection v1 — 2026-09-13

## Milestone and research purpose

Connect the ordinary XGAP profile to two independent Fuseki instances using the
already frozen FinBench same-facts mapping. This removes an engine-name assumption
that would otherwise prevent the approved XGAP-RDF / FedUP / FedX comparison.
The experimental factor is representation (native split versus same-facts RDF),
not an additional baseline variant. This milestone tests routing, executable
semantic coverage and one-shot selection; it measures no comparative speedup.

Allowed scope: frozen estimator projection, profile validation/publication, a tiny
two-Fuseki harness, relevant tests and evidence. Existing compiler and client
capabilities already separate engine from endpoint ID; reuse them. No algebra,
baseline, prompt, training weights, frozen120 population, or data rematerialization
changes. No model calls, current-query probes, alternative executions or retries.

## Algorithm and bound

Each actual endpoint retains its own ID, logical source ID, snapshot hash, row
count and width. Extract work features using those actual statistics. Then sum
each instance's five workload measures, for each match/path and full/bind family,
into its explicitly declared reference engine's existing feature dimensions.
Copy plan/coordinator features once. Apply the original frozen nonnegative scorer.
The executed plan and all source identities remain unchanged. A client must use
the declared reference engine and its explicit capability must match the instance.

Pseudocode: extract actual features; validate each used source identity; initialize
the original feature vector to zero; copy structural entries and add each instance
entry to its declared reference dimension; score the frozen vector; retain both
vectors and deployment provenance. Unknown sources/snapshots and unseen trained
categories remain unavailable, never zero-cost estimates.

For B actual instances (bounded at 64), D original dimensions and V nodes plus E
dependencies in the bounded plan, projection after feature extraction uses
O(B + D + V) time and O(B + D) additional space; the 20 workload measures per
instance are fixed. Existing feature extraction/plan traversal remains polynomial
in V, E and descriptor size. This does not enlarge the Ptime candidate domain or
execute candidates. Training artifact serialization/provenance costs are also
linear in the fixed artifact size. The enclosing planning timer includes them;
individual prediction_elapsed_ms currently excludes final deployment-provenance
serialization and must not be presented as the entire planning cost.

Nonnegative additive represented work is monotone for componentwise increases.
This is not a guarantee about actual latency, optimal plan selection or parallel
server interference. Transfer to new sources/instances is explicitly uncalibrated;
no unconditional approximation ratio or error bound is claimed. Parent training
residual is not a transfer error bound. Preserve original weights and training
provenance; do not refit merely to remove millisecond prediction error.

## Acceptance

Targeted offline checks: identity projection agrees with the existing scorer;
two same-engine sources retain distinct work before additive projection; hash
roundtrip and source/engine mismatch rejection. Publication cannot contact a
service, fit a model, read query/reference data, or accept changed load bytes.

Then one tiny live gate reuses the accepted 8-entity/16-relationship materialization
and runs the three financial semantic families on two owned Fuseki instances.
Each family estimates legal plans, selects once before service startup and executes
only that selected plan. Independent answers are read after result sealing. Keep
raw calls, the first failure and service shutdown evidence. No old success gate
is repeated. This is deterministic integration, not NL quality or paper evaluation.

After this milestone, report and pause until 2026-09-14 12:00 Asia/Shanghai per
the user's latest instruction. The overall Goal remains active and incomplete.
