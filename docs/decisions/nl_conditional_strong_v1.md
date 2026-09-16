# NL conditional strong first evaluation — 2026-09-16

User resumed engineering and authorized a first evaluable real SF0.1 result.
Performance tuning and the next discrepancy definition are not prerequisites.

User clarification (Sep16): EXACT engineering/evaluation must be unattended.
Do not ask the user to resolve or validate individual benchmark questions. Use
available frozen catalog/schema/data evidence within the declared budget; never
substitute gold, a per-question authority fixture, or model confidence for that
evidence. If the configured autonomous evidence is insufficient, record an
unresolved/failure outcome rather than suspend the campaign for human input.
The present NL profile has no human/fixture clarification tool at all. Future
automatic acquisition must keep its scope and cost visible; intent correctness
still requires independent evaluation rather than a claim from the validator.

## Input and claim boundary

The new `xgap-nl-strong-exact` / `xgap-nl-strong-performance` methods receive only
natural-language text and generic, frozen schema/catalog/backend descriptions.
A single existing compact-v2 model call (K=1, no repair) generates the semantic
program and source assignment. No per-question template, gold operators, reference
answer or preselected source assignment enters inference. Baseline labels are
“same NL frontend + FedX/FedUP”; their author algorithms remain unchanged.

`ModelStructureProposal` is a host-controlled opt-in, bound to program content and
placement. It is not `BindingEvidence`. The existing trusted-template API still
requires `$structure` validation; the NL API rejects simultaneous trusted-structure
claims. Strongness is conditional on the generated query. Neither type checking
nor EXACT validates the user's intended meaning. Exact result matching is assessed
independently after sealing the execution record; failures score zero, including
when the reference is empty.

The common frontend performs bounded frozen-artifact grounding. Its chosen values
do not replace the original holes before authority admission. EXACT requires
authoritative singleton evidence for every declared hole. PERFORMANCE may use
explicitly reported predictions. Unsupported ambiguity may therefore yield no
EXACT plan. Literal values supplied by the model remain part of the unverified
structure, even if there are no holes. Do not claim universal plan availability.

## First frozen profile

- One existing compact-v2 prompt/model/config, K=1, at most 4096 output tokens,
  at most one model call and one final execution per method/question.
- Same common frontend and grounding budgets for both modes. EXACT permits the
  existing bounded physical improvement; PERFORMANCE executes its feasible seed.
  Both retain existing global caps and unknown cost handling. No current-query
  alternative execution, refit, retry or result truncation.
- Existing frozen SF0.1 data, catalog, estimator, engine artifacts and RDF summary
  are reused. Any new serving association is a new file; original artifacts remain
  unchanged. Offline builds are one-time costs, not added as per-query acquisition.
- Twelve unique questions: first four in each of the three families in the previous
  frozen order. Selection reads no reference rows or method outcomes. Native has
  24 cells; same-facts RDF has 48 cells including the unchanged external engines.
  This is a historically exposed subset of the earlier 48-question authored
  workload, not twelve official FinBench tasks or an unseen holdout.
- One observation per cell; balanced method order, 180-second common guard,
  existing source/worker memory and communication budgets. Preserve all failures
  and unavailable usage. Source startup/loading/scoring remain separate.

This version measures NL end-to-end effectiveness and resource cost. With a fixed
frontend and no interactive acquisition branches, it cannot establish the proposed
clarification/token Pareto mechanism. K>1 policy integration, d/risk certification,
mode tuning and scaling sweeps remain later milestones. No global optimality,
calibrated error bound, significance, or SOTA superiority is assumed.

## Acceptance and outputs

First test the new identity/authority/cost boundary on tiny graphs, then one live
NL request on existing eight-node Neo4j/Fuseki stores. Commit and freeze the first
pass before evaluation. Do not debug by rerunning failed SF0.1 cells.

Report separately: valid interpretation, feasible plan, completed execution,
exact normalized answer match, nonempty answer match, full online time, LLM time
and tokens, planner CPU/wall time, execution time, source calls/bytes, and failures.
Planner wall time is not end-to-end latency; wall time is not CPU time.
Native and RDF must have separate plots/tables; external failures cannot be used
as speedup denominators. One-time costs may later be amortized explicitly.
