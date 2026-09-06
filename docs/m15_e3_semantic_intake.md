# M15-E3 Deterministic Semantic Intake and Artifact Resolution

## Status

M15-E3 is implemented locally as a controlled development gate. It connects a
natural-language request to typed semantic holes and then routes those holes
through the existing bounded goal loop using versioned local catalog and
ontology tools. It makes no backend or model call and remains
`paper_result=false`.

## Boundary

E3 is not a general natural-language parser. A versioned intake template must
declare every phrase that can bind a semantic hole or constraint. Matching is
Unicode-normalized, exact, deterministic, and longest-unique. Missing required
phrases or equal-specificity ambiguity fail closed. The template also declares
the semantic operator DAG, but it cannot contain Cypher, SPARQL, GQL, or other
native query text.

The development request is:

> 查找过去一个月与 Alice 有密切资金往来的高风险公司。

The template constructs four existing semantic operators:

1. `Match` the person-transfer fragment;
2. `Match` the company-risk fragment;
3. coordinator `Join` the aligned company identities;
4. `Project` the answer fields.

It declares four holes: entity identity, transfer predicate, relationship-
strength constraint, and company risk type. Treating `密切` as only a predicate
would silently choose one meaning, so the development catalog retains both an
amount-threshold and a frequency-threshold interpretation. The one-month window
and clarified identity policy are hard constraints; relationship strength and
risk-type adjacency are relaxable. E3 does not add or redefine an algebra
operator.

## Tools and environment

The agent sees only these E3 actions:

- `semantic.catalog.lookup`: exact normalized mention lookup over one
  immutable artifact;
- `semantic.ontology.lookup`: at most one declared adjacency hop for predicate
  or type candidates;
- `user.clarify`: apply one already collected, in-set user identity choice.

Catalog and ontology reads report zero external calls. User clarification is
an external action and reports one call. Every tool result carries a source ID,
raw artifact SHA-256, version, matching or expansion policy, and evidence.
Candidate overflow is an error rather than silent truncation. Tool failures
are not retried.

Ontology input is limited to predicate and type holes. Calling it with an
entity, source, or constraint hole fails before any external action. A catalog lookup for
the mention `Alice` deliberately yields two identities and is not
authoritative. Only an explicit user choice can reduce that set to one
authoritative binding. Without a user tool the goal stops as `blocked` before
predicate or ontology work.

The controlled development run uses this action sequence:

```text
entity catalog -> user clarification -> predicate catalog -> ontology
  -> relationship-strength catalog -> type catalog
```

It uses six tools in total: four local catalog reads, one local ontology
read, and one explicit user interaction. It uses zero LLM and zero backend
calls. The remaining non-entity candidate sets are inputs to deterministic
interpretation enumeration; they are not claimed to be the user's resolved
intent.

## Artifacts

- `experiments/configs/m15_e3_financial_risk_intake_dev.json`
- `experiments/specs/m15_e3_financial_risk_catalog_dev.json`
- `experiments/specs/m15_e3_financial_risk_ontology_dev.json`

These are controlled development fixtures, not domain truth. They exist to
validate the interface and routing contract. A production or benchmark family
must bind its own independently sourced catalog/ontology artifacts and hashes.

## Acceptance

Focused acceptance covers:

- deterministic repeatability and stable template/question hashes;
- typed hole and constraint construction;
- required-phrase, symlink, hash-drift, malformed-schema, and native-text
  rejection;
- ambiguous versus unique authoritative entity catalog behavior;
- one-hop predicate/type expansion with provenance;
- ontology rejection of entity identity;
- no silent candidate truncation;
- in-set authoritative user selection and out-of-set rejection;
- the six-action end-to-end route and execution-memory records;
- explicit preservation of amount-versus-frequency ambiguity in a constraint
  hole that ontology cannot resolve;
- the no-user blocking route with zero ontology and model calls.

The example is:

```bash
PYTHONPATH=src python examples/m15_semantic_intake_demo.py
```

Current local verification passes 27 focused E3/E1 tests and 48 combined
E1--E3 regression tests. The last full-suite gate before the constraint-hole
correction passed 993 tests with 36 explicitly gated skips; the corrected full
count is refreshed at the next repository-wide acceptance gate.

## Limits and next gate

E3 does not establish open-domain parsing quality, ontology quality, user
interaction latency, answer quality, or optimizer performance. It does not
execute the resulting candidate interpretations. The next implementation gate
must bind the E3 resolution result to deterministic semantic-class enumeration
and the existing executable-family registry without allowing hard constraints
or clarified identity to change. A UI remains optional; its first useful role
would be transporting `user.clarify`, not displaying a fabricated answer.
