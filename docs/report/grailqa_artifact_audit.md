# M13-A GrailQA Paper Artifact Feasibility Audit

## 1. Executive Summary

**Recommendation: suitable with restrictions.** GrailQA can supply a frozen
paper artifact for a conservative XGAP semantic-interpretation subset, but it
cannot yet be treated as an integrated or executable XGAP benchmark.

The audit classified all 64,331 public questions. Of the 51,100 train/dev
questions with public gold logical forms, 23,156 lower through the unchanged
production `PathPatternQuery -> LogicalPlan` pipeline. This is 45.315% of the
gold-available set and 35.995% of all public questions. Public test contains
13,231 questions but masks every field except ID and question text, so its zero
support count is an artifact-availability result, not a semantic failure.

The supported fragment is deliberately narrow: one edge, one entity anchor,
one answer class, no aggregation/comparison/superlative, and a forward relation
or an inverse declared by the official ontology. The audit-only converter
documents rather than hides its future data mapping: Freebase MIDs must be
available as a `freebase_id` node property and Freebase class membership must be
projected to XGAP labels. No production planner, pattern, algebra, semantic
deviation, physical-planning, GP, or LLM code was changed.

## 2. Dataset Availability

The data archive came from the [official GrailQA site](https://dki-lab.github.io/GrailQA/)
and is distributed there under CC BY-SA 4.0. The processed ontology came from
the [official GrailQA repository](https://github.com/dki-lab/GrailQA) at commit
`bc15df916ca4101f773722151c90ba3f9eff9df5` (repository license Apache-2.0).

| Split | File | Questions | Public gold |
|---|---|---:|---|
| train | `grailqa_v1.0_train.json` | 44,337 | yes |
| dev | `grailqa_v1.0_dev.json` | 6,763 | yes |
| test_public | `grailqa_v1.0_test_public.json` | 13,231 | no |
| total | JSON arrays | 64,331 | 51,100 |

Train/dev records provide question, answer objects, function, graph-query nodes
and edges, SPARQL, domains, and S-expression. Dev also provides the
generalization level. Test-public provides only anonymized `qid` and question.
Answers distinguish entity/value answers and include a Freebase MID or literal;
entity answers also include a friendly name.

The archive SHA-256 is
`7717dbae47ba4f6aa8b9df0810db8211460116647c0c06bb26a6b198d0aaa992`.
Per-file and ontology hashes are frozen in
`datasets/grailqa_audit/audit_summary.json`.

Missing public resources are hidden test gold annotations, a complete entity
alias catalog, a schema alias lexicon, and an XGAP/Freebase backend mapping and
graph snapshot. The Freebase data dump is referenced by GrailQA setup guidance
but is not part of the dataset ZIP audited here.

## 3. Gold Query Analysis

GrailQA supplies SPARQL, a graph-query object, and a compact S-expression for
train/dev. The observed S-expression calls are `AND`, `JOIN`, reverse `R`,
`COUNT`, `ARGMAX`, `ARGMIN`, and lowercase `lt`, `le`, `gt`, `ge` comparisons.
Grounded leaves are Freebase entity IDs or typed literals. Graph queries contain
one to four relation edges and systematically add type and pairwise-distinctness
constraints in SPARQL.

| Gold construct | Questions | Occurrences | Current audit support | Status |
|---|---:|---:|---|---|
| relation traversal (`JOIN`) | 47,792 | 63,986 | direct one-hop only | partial |
| class/intersection (`AND`) | 48,724 | 52,963 | endpoint classes only | partial |
| reverse relation (`R`) | 12,451 | 16,474 | direct one-hop orientation only | partial |
| entity constraint | 42,563 | n/a | one endpoint MID mapping | partial |
| literal constraint | 9,971 | n/a | no | unsupported |
| count | 2,744 | 2,744 | no | unsupported aggregation |
| comparison | 2,391 | 2,379 calls | no | unsupported comparison |
| superlative (`ARGMAX`/`ARGMIN`) | 3,146 | 3,146 | no | unsupported ordering |
| multi-hop graph | 15,654 | n/a | no exact conversion | unsupported path semantics |
| branching graph join | 686 | n/a | no | outside `PathPatternQuery` |

The 12-question difference between comparison function labels and parsed
comparison calls is retained as an observed source-representation difference;
the function label governs conservative classification.

## 4. XGAP Lowering Feasibility

The isolated converter reads the gold graph-query and S-expression. A supported
record becomes:

1. source `NodePattern`: entity class plus `freebase_id=MID`;
2. one `Rel(EdgePattern)`: gold relation, or its official inverse when needed;
3. target `NodePattern`: gold answer class;
4. `PropertyNotEquals(last.freebase_id, source MID)` to preserve the one-edge
   GrailQA distinctness constraint;
5. `Selector(ALL)` and `SIMPLE` restrictor;
6. existing type check, deterministic lowering, validation, and plan indexing.

Every supported plan has seven operator occurrences and six dependencies:
`Edges`, four `Selection` calls, `GroupBy`, and `Projection`. No new logical
operator name or benchmark-specific production lowering exists.

The path is always oriented from the entity anchor to the answer. A graph edge
from entity to answer uses its declared predicate directly; an edge from answer
to entity requires `reverse_properties`. This orientation is not identical to
the surface `R` marker in GrailQA's set-valued S-expression grammar, so the
audit uses the graph-query edge endpoints as the authoritative direction.

Multi-hop conversion is rejected because current `PathPatternQuery` cannot
attach class descriptors to intermediate nodes or express all pairwise node
inequalities for a fixed sequence. Branching conjunctions are outside the
path-centric query object. Dropping those constraints would be a semantic
change, so the audit does not do it.

The support result is logical-structure feasibility, not backend executability.
The documented MID/type projection must become a validated DatasetBundle
mapping before reference answers or native Freebase execution can be claimed.

## 5. Supported Fragment Ratio

| Population | Supported | Total | Ratio |
|---|---:|---:|---:|
| all public | 23,156 | 64,331 | 35.995% |
| train/dev with gold | 23,156 | 51,100 | 45.315% |
| train | 19,840 | 44,337 | 44.748% |
| dev | 3,316 | 6,763 | 49.031% |
| public test | 0 | 13,231 | 0% (gold masked) |
| no-function train/dev | 23,156 | 42,819 | 54.079% |
| one-edge train/dev | 23,156 | 35,446 | 65.328% |

Within dev, support is 510/1,514 compositional (33.686%), 723/1,593 i.i.d.
(45.386%), and 2,083/3,656 zero-shot (56.975%). Train has no public `level`
field, so no generalization-level claim is made for it.

## 6. Unsupported Taxonomy

| Reason | Questions | Meaning |
|---|---:|---|
| `missing_gold_logical_form` | 13,231 | public test annotations are masked |
| `unsupported_path_semantics` | 12,671 | multi-hop/intermediate constraints or branching |
| `missing_entity_mapping` | 4,343 | no single entity endpoint under the audit contract |
| `unsupported_ordering` | 3,146 | argmax/argmin/max/min |
| `unsupported_aggregation` | 2,744 | count |
| `missing_relation_mapping` | 2,635 | 2,620 lack a declared inverse; 15 lack predicate metadata |
| `unsupported_comparison` | 2,391 | numeric/date comparison |
| `missing_ontology_term` | 14 | endpoint class absent from parsed official metadata |

These categories are mutually exclusive under the converter's deterministic
decision order. They are feasibility diagnostics, not accuracy labels.

## 7. Ontology Artifact Analysis

The official repository provides `fb_roles` (domain/range), `fb_types`
(subclass), `reverse_properties`, `domain_dict`, and `domain_info`.

| Resource statistic | Count |
|---|---:|
| classes | 10,656 |
| object-valued relations | 13,747 |
| scalar-valued properties | 5,531 |
| known scalar datatypes | 11 |
| predicates total | 19,278 |
| unique hierarchy edges | 18,235 |
| reverse-property pairs | 4,954 |
| schema terms with annotation labels | 4,278 |
| entity IDs with train/dev labels | 26,736 |
| public alias lists | 0 |

Four source lines are concatenated/malformed: `fb_roles` lines 5,608 and
16,612, and `fb_types` lines 12,779 and 14,394. The unique hierarchy also has
16 self-edges and 10 cyclic strongly connected components covering 18 terms.
M12 `OntologyGraph` requires an acyclic hierarchy, so direct loading is not
valid.

- `ontology.yaml`: feasible only after documented source normalization,
  category policy, cycle handling, and M12 validation.
- `aliases.yaml`: not constructible from public artifacts alone. Friendly names
  are canonical annotation labels, not a complete alias lexicon.
- `schema_snapshot.json`: constructible after freezing the normalization and
  Freebase-to-XGAP mapping policy.
- entity catalog: partial train/dev construction is possible; test and complete
  Freebase coverage are unavailable.

No ontology edge or alias was inferred, and no LLM was used.

## 8. Anchor Feasibility

Gold graph queries deterministically expose class, relation/property, datatype,
and entity-ID slots. Therefore `S(u)` and exact gold anchors `a_u(s)` can be
extracted for 51,085/51,100 gold-available questions (99.971%). The remaining
15 reference relations are absent because of malformed/missing source metadata.
Public test's 13,231 questions cannot receive gold anchors from released
artifacts.

Only 23,156 questions are both gold-slot anchorable and convertible to the
current XGAP reference query. This lower count is the relevant one for a frozen
restricted XGAP paper subset. It does not require or claim natural-language
anchor generation.

## 9. Complexity Distribution

For supported XGAP plans, `Q(u)=|Omega|+|D|` is exactly 13 for all 23,156
questions: mean 13, median 13, p90 13, maximum 13, histogram `{13: 23156}`.
This uniformity follows from the intentionally one-edge support boundary.

As supplemental workload characterization, the parsed gold S-expression
operator-call trees have mean 4.546, median 3, p90 9, and maximum 17. Their
histogram is `{1:1973, 3:31314, 5:4458, 7:6624, 9:4362, 11:1500,
13:572, 15:266, 17:31}`. This second measure is explicitly a gold syntax-tree
proxy; unsupported trees are not mislabeled as XGAP `LogicalPlan`s.

## 10. Ambiguity Feasibility

The public class hierarchy, domain/range records, reverse properties, and exact
gold ontology slots make a later ontology-neighborhood ambiguity protocol
possible after normalization. They do not provide ambiguity labels or reference
interpretation sets, and M13-A does not generate them.

To compute a future `A(u)` without hidden assumptions, XGAP still needs a frozen
acyclic ontology, complete alias/entity artifacts for the evaluated split, a
documented candidate-construction policy, a fixed `epsilon_amb`, and reference
interpretations validated under the same DatasetBundle mapping. Public test
would additionally require official evaluation access or released gold.

## 11. Recommendation

Use GrailQA in paper experiments only as an explicitly named, frozen
**restricted train/dev semantic-interpretation subset** after building and
validating the missing DatasetBundle mapping and normalized ontology artifacts.
Do not report the 23,156-question audit set as full GrailQA coverage, do not use
public test for gold semantic metrics, and do not treat unsupported constructs
as negative model outcomes.

The next integration task should freeze question records, mappings, ontology,
aliases/entity coverage policy, gold reference interpretations, and answer
evaluation for the selected subset. This audit alone does not complete any of
those steps.

## Machine-Readable Artifacts

- `datasets/grailqa_audit/audit_summary.json`
- `datasets/grailqa_audit/supported_questions.jsonl`
- `datasets/grailqa_audit/unsupported_questions.jsonl`
- `datasets/grailqa_audit/ontology_summary.json`
- `datasets/grailqa_audit/complexity_distribution.json`
