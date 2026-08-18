# M13-B KQA Pro Paper Artifact Feasibility Audit

## 1. Executive Summary

**Recommendation: unsuitable** as the primary current XGAP benchmark for
end-to-end execution, physical planning, cost estimation, or scalability.
KQA Pro remains useful as a future integration target and as a restricted
diagnostic source.

The audit classified all 117,970 public questions. Train and validation expose
106,173 paired KoPL programs, SPARQL queries, and answers; public test exposes
11,797 questions and choices but masks all gold fields. Exactly 1,690
train/validation records lower through the unchanged `PathPatternQuery ->
LogicalPlan` path and pass both M9 native compiler probes. This is 1.592% of
gold-available questions and 1.433% of all public questions.

The supported audit fragment is deliberately strict: a linear `Find`, one or
two uniformly directed `Relate` steps with concept filters, and terminal
`What`. Backward programs are represented by reversing the fixed physical path;
mixed-direction paths are rejected. The audit does not approximate qualifiers,
attributes, aggregation, comparison, ordering, set operations, or scalar and
Boolean answers.

Native compilation is structurally feasible for these 1,690 records under an
ephemeral in-memory RDF term probe. Current KQA Pro execution coverage is still
zero because the repository has no final KQA Pro DatasetBundle, Neo4j/RDF
mapping, loader, answer extractor, or loaded backend snapshot. M13-B therefore
does not claim benchmark integration or answer correctness.

## 2. Dataset Availability

The official baseline repository is
[`shijx12/KQAPro_Baselines`](https://github.com/shijx12/KQAPro_Baselines),
audited at commit `14d87cd22eb79f702fd4ad5c09240bef126d9dce`. Its README
documents four dataset files but does not version them in Git.

The documented Tsinghua Cloud download returned `Link does not exist` during
this audit. The complete public mirror
[`drt/kqa_pro`](https://huggingface.co/datasets/drt/kqa_pro), revision
`0b26da66cec9a4d1e42bde3560aeae9f89f6433b`, supplied byte-complete files whose
SHA-256 values match the mirror's LFS object identifiers.

| Split/artifact | Records | Gold KoPL/SPARQL/answer | SHA-256 |
|---|---:|---|---|
| `train.json` | 94,376 | yes | `e9fbe4c1cdf207aac83ae0d5e4a1a53a9965a2b13b403de699ca6d5dae6e4510` |
| `val.json` | 11,797 | yes | `b4aed6ab3d7ad071722064fe3bb02bc028cfbeb15da5f7115d57a1e2d198f3bb` |
| `test.json` | 11,797 | no | `b2142ed6124ae525b7d7fd8d1edb338c1b025751ac0167ff1498608111911822` |
| `kb.json` | 794 concepts, 16,960 entities | KB metadata | `04da7408320c5cb7023c44372cce32846d56d369d8865d2e61a18c3956661a7c` |

The official README states CC BY-SA 4.0, whereas the mirror metadata says MIT.
This license-metadata conflict must be resolved from the dataset owner before a
paper artifact is redistributed. The audit records the official README claim
and does not reinterpret the license.

No separate schema, ontology, alias, or relation-domain/range file was found.
The KB is the only schema-bearing data artifact.

## 3. Question, Program, and Answer Structure

Train/validation records contain:

- `question`: natural-language string;
- `choices`: ten answer strings;
- `program`: ordered KoPL calls with `function`, explicit earlier-step
  `dependencies`, and lexical `inputs`;
- `sparql`: one generated SPARQL string;
- `answer`: one gold answer string.

Test records contain only `question` and `choices`. They cannot support gold
conversion, answer evaluation, or oracle construction from public artifacts.

KoPL uses names, relation strings, attribute strings, values, and directions in
program inputs rather than KB identifiers. `kb.json` supplies `Q...` concept and
entity IDs, canonical names, direct `instanceOf` links, observed attributes,
relations, directions, and fact qualifiers. SPARQL uses generated predicate
tokens such as `<pred:name>` and underscore-normalized relation names. Answers
are strings, including entity names, numbers with units, dates/years, and
`yes`/`no`; they are not typed answer objects.

## 4. KoPL Coverage

All 27 operators implemented by the official rule executor occur in the gold
train/validation programs.

| KoPL operator | Occurrences | Questions | XGAP mapping | Status |
|---|---:|---:|---|---|
| `FindAll` | 34,132 | 31,756 | `Nodes(G)`, but no edge-bearing query seed | partial |
| `Find` | 144,515 | 79,544 | endpoint name predicate | partial |
| `FilterConcept` | 67,604 | 53,058 | `LabelEquals` on a path node | partial |
| `FilterStr` | 28,569 | 27,563 | property equality requires a fact-representation policy | unsupported |
| `FilterNum` | 10,520 | 10,119 | quantity/unit comparison | unsupported |
| `FilterYear` | 4,660 | 4,414 | typed temporal comparison | unsupported |
| `FilterDate` | 4,069 | 4,034 | typed temporal comparison | unsupported |
| `QFilterStr` | 2,702 | 2,702 | relation/attribute fact qualifier | unsupported |
| `QFilterNum` | 647 | 647 | relation/attribute fact qualifier | unsupported |
| `QFilterYear` | 1,458 | 1,458 | relation/attribute fact qualifier | unsupported |
| `QFilterDate` | 584 | 584 | relation/attribute fact qualifier | unsupported |
| `Relate` | 56,631 | 46,378 | `Rel`, with `Seq` for a uniform direction | partial |
| `And` | 28,539 | 26,208 | entity-set intersection is not a path `Join` | unsupported |
| `Or` | 4,308 | 4,308 | entity-set union is outside the audited fragment | unsupported |
| `What` | 12,632 | 12,632 | path answer-endpoint extraction | partial |
| `Count` | 12,264 | 12,264 | entity-set cardinality | unsupported |
| `SelectBetween` | 14,851 | 14,851 | attribute comparison and entity selection | unsupported |
| `SelectAmong` | 4,836 | 4,836 | attribute ordering and entity selection | unsupported |
| `QueryAttr` | 25,022 | 25,022 | scalar attribute projection | unsupported |
| `QueryAttrUnderCondition` | 917 | 917 | qualified scalar projection | unsupported |
| `VerifyStr` | 6,345 | 6,345 | Boolean scalar verification | unsupported |
| `VerifyNum` | 2,250 | 2,250 | Boolean scalar verification | unsupported |
| `VerifyYear` | 4,311 | 4,311 | Boolean scalar verification | unsupported |
| `VerifyDate` | 194 | 194 | Boolean scalar verification | unsupported |
| `QueryRelation` | 15,662 | 15,662 | edge-label projection between entities | unsupported |
| `QueryAttrQualifier` | 10,875 | 10,875 | attribute qualifier projection | unsupported |
| `QueryRelationQualifier` | 9,114 | 9,114 | relation qualifier projection | unsupported |

The table does not equate KoPL `And`, `Or`, or `Count` with similarly named or
adjacent algebra concepts. Their data objects and result semantics differ from
the current `PathPatternQuery` contract.

## 5. SPARQL Coverage

Gold SPARQL has mean 5.670 statement-terminated patterns, median 6, p90 8, and
maximum 13. The deterministic surface audit found:

| Feature | Questions |
|---|---:|
| repeated-variable joins | 106,173 |
| ordering | 19,687 |
| union | 19,165 |
| filters/comparisons | 13,830 |
| aggregation | 12,264 |
| qualifier fact reification | 25,244 |
| nested `SELECT` | 3 |
| optional patterns | 0 |
| property-path syntax | 0 |

These counts are lexical measurements of KQA Pro's generated SPARQL, not a
general SPARQL parse. Bracketed fact reification counts as one statement.

The audit converter is paired rather than SPARQL-only: explicit KoPL
dependencies determine the reference path, while the corresponding SPARQL must
pass a compatible fixed-path surface guard. This avoids inventing a second
general SPARQL parser and still rejects any disagreement that exposes
aggregation, filters, union, ordering, subqueries, or qualifier reification.

## 6. XGAP Lowering Feasibility

A supported program must satisfy all of the following:

1. start with `Find` and end with `What`;
2. use only linear predecessor dependencies;
3. contain one or more `Relate` steps, each followed by explicit concept
   constraints as present in the gold program;
4. use one direction throughout;
5. resolve every relation and concept from `kb.json` without an ambiguous
   concept name;
6. have a compatible fixed-path gold SPARQL surface.

Forward programs become a source name constraint, fixed `Rel`/`Seq` expression,
intermediate `NodeRef` label constraints, and target concept constraint.
Backward programs reverse the edge sequence and node positions so that every
physical edge remains `Direction.OUT`; the answer endpoint becomes the physical
source. This uses existing semantics rather than adding reverse lowering.

Every candidate then passes existing path-pattern type checking, production
lowering, logical validation through the lowering boundary, deterministic plan
indexing, M9 compiler-input extraction, and both native compilers. The SPARQL
compiler receives an ephemeral complete term probe made only from explicit KB
terms. That probe is not written as a mapping artifact and proves syntax-level
compiler feasibility only.

| Population | Supported | Total | Ratio |
|---|---:|---:|---:|
| train | 1,497 | 94,376 | 1.586% |
| validation | 193 | 11,797 | 1.636% |
| train + validation gold | 1,690 | 106,173 | 1.592% |
| all public questions | 1,690 | 117,970 | 1.433% |
| public test | 0 | 11,797 | gold masked |

The 1,690 records contain 1,561 one-hop and 129 two-hop paths. Six otherwise
structural candidates are rejected because their concept names map to multiple
KB concept IDs. Another 242 use mixed forward/backward steps that cannot be
represented by one directed path orientation.

## 7. Unsupported Taxonomy

The mutually exclusive decision order produced:

| Reason | Questions |
|---|---:|
| qualifier semantics | 25,244 |
| ordering/entity comparison | 19,687 |
| public test gold unavailable | 11,797 |
| aggregation | 12,020 |
| Boolean comparison/verification | 11,198 |
| entity-set `And`/`Or` | 10,475 |
| scalar attribute projection | 9,156 |
| relation projection | 8,927 |
| attribute fact representation | 4,120 |
| typed quantity/date/year semantics | 3,408 |
| mixed path direction | 242 |
| ambiguous concept name mapping | 6 |

Counts reflect classification priority. For example, a query containing both a
qualifier and `Count` is assigned to qualifier semantics, so category totals
need not equal raw operator occurrence counts.

## 8. Ontology and KB Availability

| KB evidence | Count |
|---|---:|
| concepts/classes | 794 |
| entities | 16,960 |
| direct concept hierarchy edges | 365 |
| observed relation names | 363 |
| observed attribute names | 629 |
| observed qualifier keys | 275 |
| relation facts | 415,334 |
| attribute facts | 174,539 |
| qualifier values | 309,407 |

The concept hierarchy is acyclic in the released KB. Three concept names and
1,805 entity names are duplicated. Duplicate entity names are compatible with
KoPL's set-valued `Find` behavior; duplicate concept names are not silently
collapsed by the audit.

An `ontology.yaml` is constructible after freezing canonical identifier,
transitive class-membership, and concept-name collision policies. An entity
catalog is constructible from the complete KB. An observed schema snapshot is
also feasible, but the data does not provide declared relation domain/range or
attribute cardinality metadata. Canonical names are not an alias lexicon, so an
`aliases.yaml` cannot be claimed from these artifacts alone.

## 9. Backend Mapping Feasibility

For Neo4j, a faithful restricted loader can create concept/entity nodes with a
stable KQA ID and name, materialize transitive concept membership as labels,
and create each canonical forward relation once. Attribute facts are
multi-valued and qualified; flattening them into scalar properties would not be
faithful without a proved per-key policy. The supported M13-B subset avoids
that issue.

For Fuseki, stable absolute IRIs can represent KQA IDs, relation names, and
concepts. The loader must materialize the class closure expected by
`FilterConcept`, map `name` consistently, and preserve only one canonical copy
of facts represented in both KB directions. The official generated tokens are
not themselves a frozen XGAP RDF mapping.

Both backends therefore have a feasible mapping for the strict path subset,
but no final mapping is created here. Required unresolved decisions include
IRI/label encoding, duplicate concept names, transitive type materialization,
attribute/value-node representation, qualifiers, units/datatypes, and answer
endpoint normalization.

## 10. Execution Feasibility

The audit distinguishes three facts:

- **semantic support:** 1,690 records produce a reference
  `PathPatternQuery` and logical plan;
- **native compilation feasibility:** all 1,690 emit Cypher and SPARQL under
  explicit audit-only mapping assumptions;
- **current end-to-end executability:** 0 records, because no KQA Pro
  DatasetBundle, final mappings/loaders, backend snapshot, or answer normalizer
  exists in the repository.

M9 returns full path row bindings. A future integration must select the correct
physical endpoint, project its name, deduplicate entity answers, and compare
against KQA Pro's string answer contract. Compilation alone is not answer
equivalence.

## 11. Physical Planning Feasibility

M11 plans the M9 compiler fragment, which excludes selector-only `GroupBy` and
`Projection` wrappers. Exact planning complexity is:

| Path length | Queries | `|Omega|` | `|D|` | `Q(u)` |
|---|---:|---:|---:|---:|
| one hop | 1,561 | 4 | 3 | 7 |
| two hops | 129 | 8 | 7 | 15 |

Across supported queries, `Q(u)` has mean 7.611, median 7, p90 7, and maximum
15. Full reference plans, including the ALL-selector wrappers, have mean
11.611, median 11, p90 11, and maximum 19.

Neo4j and Fuseki each support every planning operator conditionally, yielding
two placement choices per operator. The unconstrained placement product is 16
for one hop and 256 for two hops. With the current empty exchange catalog, only
two complete realizations are executable in principle: all Neo4j or all Fuseki;
cross-backend realizations are zero. M11's conservative state-space bound is 31
or 511.

All 1,690 supported records fit the controlled oracle limit of 4,096 states and
are listed in `oracle_candidates.jsonl`. No exhaustive oracle was executed
because M13-B collects no true backend costs. The subset's two topology shapes
and maximum two hops are insufficient for a persuasive primary scalability or
search-space study.

## 12. Cost-Model Feasibility

After backend integration, the 1,497 supported train records could supply a
frozen calibration/D0 pool, the 193 supported validation records an evaluation
pool, and a deterministic remainder order an online task stream. The public
test split cannot support gold-stratified evaluation.

No calibration or backend measurement was run. A paper protocol still needs a
loaded immutable KB snapshot, final mappings, repeated timing policy, warmup and
cache controls, timeout/error policy, answer validation, and split leakage
checks. More importantly, the supported plans have only two topology sizes, so
KQA Pro's semantic diversity does not become physical-plan diversity under the
current XGAP fragment.

## 13. Ambiguity Feasibility

Train/validation KoPL programs and the KB hierarchy expose gold concept and
relation slots from which a future ontology-neighborhood candidate set could be
constructed. That can support reference `c_sem` inputs after a DatasetBundle
and mapping policy are frozen.

KQA Pro does not supply ambiguity labels or aliases. Duplicate names are
evidence of lexical collision, not gold ambiguity sets. M13-B generates no
candidate interpretations, semantic-deviation values, or LLM prompts.

## 14. Recommendation

Do not use KQA Pro as the main current XGAP paper benchmark. The 1.592%
gold-supported fragment is too narrow, currently has zero integrated execution
coverage, and yields only one- and two-hop planning shapes with two backend-local
realizations.

KQA Pro can be retained as a future restricted diagnostic benchmark after a
separate integration milestone supplies frozen loaders, mappings, answer
normalization, and live validation. Broader coverage would require explicit
future semantic work for scalar results, fact qualifiers, typed values,
aggregation, comparisons, set operations, and mixed-direction patterns. Those
extensions are not part of this audit.

## Machine-Readable Artifacts

- `datasets/kqapro_audit/audit_summary.json`
- `datasets/kqapro_audit/supported_questions.jsonl`
- `datasets/kqapro_audit/unsupported_questions.jsonl`
- `datasets/kqapro_audit/kopl_operator_statistics.json`
- `datasets/kqapro_audit/sparql_statistics.json`
- `datasets/kqapro_audit/ontology_summary.json`
- `datasets/kqapro_audit/complexity_distribution.json`
- `datasets/kqapro_audit/oracle_candidates.jsonl`
