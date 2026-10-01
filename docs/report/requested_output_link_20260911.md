# Explicit output contract accepted; five real responses expose remaining interpretation errors

2026-09-11. Parent `4d5b194a97b9dedc2d67fe3fbbd2bc2ee5a43737`, with separately
fingerprinted source changes. This is a bounded LINK development diagnostic for
R-E, not a paper benchmark or a completed NL-to-answer gate.

The external `qwen3.8-27b` service is available. The preceding connection probe
and real Neo4j/Fuseki B01 execution remain documented in
[the original external report](external_toy_link_20260911.md). GPU allocation is
no longer required for this model path. No new health probe was needed here.

The previous extra `age` column was a model error: the original question already
explicitly requested person and edge. An optional request-owned
`context.requested_output` now declares the output field set before generation.
The separate `explicit-output-v1` tiny intake recognizes two explicit return
clauses in the original NL. It reads no gold, expected rows or authored program.
The v3 prompt explains the contract; parser admission rejects mismatches without
rewriting the program, fetching properties or dropping columns. Legacy requests
and prompt v2 remain unchanged. See the
[bounded contract](../decisions/requested_output_contract_v1.md).

The contract checks exactly one BindingSet root, currently final Project or
Match. It proves neither field lineage nor values nor the whole question's
meaning. This is a finite development intake, not a general NL output parser.

## Actual results

After the focused tests and zero-call preflight, all five unchanged questions
were each sent once with the new versioned request and prompt. There was no
repair, retry, altered gold or success-selected population.

| Question | Input tokens | Output tokens | Interpretation seconds | Admission |
|---|---:|---:|---:|---|
| B01 | 1818 | 782 | 4.162 | Admitted; answer unmeasured |
| B02 | 1818 | 554 | 2.943 | Rejected: unsupported final Filter root |
| B03 | 1818 | 554 | 2.933 | Rejected: unsupported final Filter root |
| B04 | 1835 | 381 | 2.110 | Admitted; answer unmeasured |
| B05 | 1827 | 782 | 4.083 | Admitted; answer unmeasured |

Total: **5 model calls, 9116 input + 3053 output = 12169 reported tokens,
16.231 seconds of Interpretation**. Admission is 3/5; strict native accuracy is
unmeasured, not 3/5. The previous v2 parser admitted 5/5 under a weaker contract;
these numbers are not comparable answer accuracies or a causal quality estimate.
Different generated plans also prevent a latency-improvement claim.

B02/B03 return a Traverse → Project(person, edge) → Filter(age) chain. The saved
programs have no step that provides `age` and omit the requested people type.
The observed rejection is specifically the restricted final-root contract;
the missing age/type is a separate static diagnosis, not a measured database
failure. Passing output-field admission for the other three likewise does not
establish executable predicates or correct answers.

Read-only follow-up also finds a different risk in B01/B05: `eligible` is Match
but carries a binding-row `{op:ge, field:age}` condition. Match lowering uses the
path-condition parser, which requires a `kind` discriminator such as
`property_gte`. The current parser would reject that missing kind. This is a
static diagnosis, not an executed compile/backend failure. B04 uses the supported
path-condition syntax, but its answer has not been evaluated in this version.

The frozen five-question admission prerequisite failed, so the new native gate
was not started: zero database calls and all five native outcomes `not_run`.
No admitted-only subset was presented as the full cohort. Existing RDFLib test
fixtures use a different replica/version context; they cannot be substituted
into these exact recorded native requests by relabeling the environment.
The local-replay `not_run_receipt.json` records this decision and confirms all
six source recordings/result files remained unchanged; no replay was attempted.

## Focused verification and preserved evidence

The first run passed **18 new checks and 5 affected legacy parameters** in
0.45 seconds (process 0.911 seconds), with all 16 source/test/prompt hashes
unchanged. This includes one controlled loopback HTTP → ordinary P1 → tiny
RDFLib slice, explicit rejection before backend access, and exact-context replay.
It is separate from the actual external model diagnostic above.

A read-only review found that two mechanism-ablation flag combinations would
claim the new request profile without using it. The native CLI now rejects
both; only those two parse checks were added and passed. The earlier 23 checks
were not repeated. All generation-time source fingerprints were stable during
the model requests. The only subsequent source change is that native CLI guard;
the machine record lists its before/after hash explicitly.

All five old payloads were checked once against the NL-derived output contract
without modification: B04 matches; the other four retain their extra-column
mismatch. This is labeled compatibility analysis of old outputs, not replay of
a request the model never saw. Both generations, the old native strict failure,
original Qwen 0/5, FinBench prepared-plan 6/6 and original 150/48 populations remain.

Raw evidence: `/Users/anthonyche/xgap-data/requested-output-link-20260911/`.
[Machine evidence](../../experiments/artifacts/requested_output_link_20260911.json)
records the complete denominator, costs, hashes, errors and native non-execution.
The served alias/checkpoint/tokenizer limitations of the prior report still apply.

## Next bounded work

Use the saved v3 programs to address executable field/predicate semantics before
another model request. Avoid tuning prompts repeatedly against five outcomes.
Keep Interpretation quality separate from deterministic planner experiments;
real-data coverage, measured prior costs and fair E1–E5 remain on the deadline's
critical path. The independent remote job 3804210 stays untouched until the user
provides an update. This output-contract implementation is accepted in its stated
scope; the complete real-model LINK is still unfinished.
