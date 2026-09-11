# T1 typed binding values

2026-09-11; base400f0cf. This typed-binding milestone is accepted; overall Goal remains active.

## Problem and implemented behavior

The old coordinator converted large integer SUM to float, accepted numeric
strings, rejected RDF decimals, split numeric-equivalent group keys and could
not order nulls with numbers. A concrete pre-change probe is retained at
`/tmp/xgap-next-typed-binding-observations.json`.

The frozen [binding value decision](../decisions/typed_binding_values_v1.md)
now has one shared implementation used by binding Filter, Join/SemiJoin,
grouping, deduplication, aggregation and ordering. Integer sums remain exact
Python integers. Integer/decimal sums return an exact typed decimal. Floating
inputs retain the existing decimal-value accumulation followed by one final
float conversion. COUNT(field) and per-aggregate DISTINCT are executable.
MIN/MAX and sorting use one explicit scalar order, with configurable null
placement. Numeric lexical forms/ranges are checked before native RDF tags are
erased. The semantic compiler records `typed_binding_values_v1`.

This changes binding-row semantics, not audited PathSet or focused-binding
algebra. JSON Boolean true remains distinct from numeric 1 in binding values.
No new algebra operator, LLM call, GPU allocation or catalog build is involved.

## Independent fixture and concrete answers

`datasets/backbone_typed_v1` independently specifies 15 NL→semantic DAG→Match
path sub-IR/logical plan→runtime operator sequence→native reference→typed answer
chains. The original five-node/eight-edge graph and all prior gold stay frozen.
The new overlay has integer amount and RDF-only decimal credit. Explicit
logical views declare core replicas on both engines and credit on Fuseki only.
The normal planner observes, chooses and executes candidates from those views;
answers are used only for subsequent validation.

| Case | Independent expected behavior | Native result |
|---|---|---|
| V01 | 9007199254740993 + 2 | Exact integer 9007199254740995 |
| V02 | Decimal 10000000000000000000000.10 + 0.20 − 0.05 | Exact typed decimal 10000000000000000000000.25 |
| V03 | Five persons; scores 1, 1.0, true, "1", null | COUNT(*)=5, COUNT(score)=4, DISTINCT count=3 |
| V04 | Group the same five score values | Four groups; numeric group contains two persons |
| V05–V07 | Mixed scalar order, null placement, MIN/MAX | Numeric→string→Boolean; numeric ties use person; MIN=1, MAX=true |
| V08 | Numeric score=1 then sum/count | Exact amount sum and count 2; Boolean does not match |
| V09 | Join two sources on score | Six identity pairs; null does not join, 1 joins 1.0 |
| V10–V11 | Union and DISTINCT SUM | Four value rows; numeric DISTINCT sum is float 1.0 |
| V12/V15 | Empty input / all-null field | Correct counts, SUM=0, MIN/MAX=null |
| V13 | Choose Alice in core; join RDF credit; aggregate | Exact decimal 10000000000000000000000.1 |
| V14 | Sort decimal credit, missing last | Dan, Bob, Alice, Cara, Zoe |

## Gates and retained failures

- Focused final: session2033 exit0, 208 passed in5.48s.
- Daily: session7865 exit0, 489 passed in26.35s plus18 original toy demo cases.
  The initial direct shell invocation exited126 because the script is not
  executable; invoking it through bash succeeded. This was a local invocation
  correction, not a backend retry.
- Final changed-reference replay: session60153 exit0, 53 passed in1.19s.
  Independent native Jena ARQ evaluation passed15/15 reference targets locally.
- Native retained acceptance: **15/15 programs,32/32 legal candidate answers,
  27/27 independent targets, original two-engine vertical slice correct**.
  These are combined successful case records, not a fictitious single run.
- Final broad: session24384 exit0, **3334 passed/38 skipped in670.66s**, all24
  harness/example entrypoints passed. No source/test changes after its launch.
  Receipt: `experiments/artifacts/toy_backbone_t1_typed_bindings_20260911.json`.

All native stores were fresh, owned, loopback-only. Pinned Neo4j5.26.30,
Fuseki5.6.0, Java21.0.10; each service pair stopped normally without KILL.

| Native record directory under `/Users/anthonyche/xgap-data/` | Terminal outcome | Observations / serving / extra candidate validation | Independent targets |
|---|---|---|---|
| `t1-typed-binding-native-20260911` | 40877 exit1, V01 program/candidates correct; reference SUM over unbound values differed | 2 / 1 / 1 | 1/2 |
| `t1-typed-binding-native-final-20260911` | 50945 exit1, V01–V06 programs correct; V06 reference type tie-break differed | 11 / 6 / 5 | 10/11 |
| `t1-typed-binding-native-followup-20260911` | 58476 exit1, V05–V06 programs correct; casting to double still retained RDF lexical differences | 4 / 2 / 2 | 3/4 |
| `t1-typed-binding-native-completion-20260911` | 73125 exit0, V05–V15 programs and old slice correct | 26 / 14 / 21 | 20/20 |

The retained set uses V01–V04 from the second record and V05–V15 from the last.
It accounts for33 observations,18 serving calls,24 extra candidate-validation
calls,27 reference calls and2 old-slice calls. The complete development campaign
has43 observations,23 serving,29 extra validation,37 references and2 slice calls.
These counts include the recorded failed comparisons; they are not performance
measurements or independent benchmark samples. Health/load calls are separate.

Local failures are retained rather than silently counted as successes:

1. The initial floating sum used a different accumulation rule and regressed
   3.1+4.2. The old decimal-representation accumulation was restored before the
   final208-test gate; compatibility119/1 and focused153/1 failures are preserved.
2. Fixture authorship initially expected the wrong V10 numeric representative;
   Project keeps the first occurrence in deterministic person order, hence Alice's
   integer1. Reference casting also exposed RDFLib conversion/term-identity
   differences. Local runs54535 and73179 ended78/4 and81/1 respectively.
3. Jena SUM with unbound inputs did not implement the intended null-ignore
   contract; independent queries now use explicit COALESCE for SUM. Native RDF
   ordering/term DISTINCT needed canonical integral score terms, not a cast
   that preserves an existing double's lexical form. References only apply this
   conversion to the fixture's integral scores, never to amount/credit values.
4. Local Jena ARQ replay caught a reference SELECT alias collision and V11 term
   DISTINCT before further service execution. The corrected15 targets and local
   RDF tests passed before the final native follow-up.

Production coordinator code did not change between native attempts. The first
two source records differ from final only in the runner's explicit query-subset
option. Final source hashes and retained selected-plan identity are verified in
the durable receipt. Earlier artifacts and failed result.json files remain intact.

## Scope and remaining work

This is correctness evidence on a tiny graph. It establishes type-consistent
binding execution and one explicit property-source federation case. It does not
establish general source discovery, partition inference, optimal planning,
streaming execution, arbitrary native decimal support, real NL accuracy or SOTA.
Floating output retains floating precision; order/filter constants still follow
their explicitly supported interfaces. Path atomic equality remains separately
audited. Broader T1 coverage and T2/T3 are unfinished.

Next: freeze the finite profile in [bounded system scope](../decisions/bounded_system_scope_v1.md),
finish the operator-by-layer coverage boundary and included gaps, then the independent
Interpretation and deterministic chains, offline catalog freeze/runtime-only
lookup and minimal failure replay. Keep the permanent toy slice; use GrailQA-mini
for later real integration and full datasets only for final evaluation.
