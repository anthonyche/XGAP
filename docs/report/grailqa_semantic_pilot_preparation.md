# GrailQA Semantic Pilot Preparation

## Status

M13-D is **SERVER-READY**. It prepares the first live GrailQA RQ1 semantic
pilot; it does not claim that the 150-query live pilot has run. The scope ends
at interpretation generation, deterministic validation/grounding, unchanged
`c_sem`, epsilon filtering, deterministic ranking, and structural reference
evaluation. GrailQA backend execution, physical regret, RQ2, and RQ3 remain
outside this milestone.

## Inference Catalog

`datasets/grailqa_inference_catalog_v1/` is query-independent and contains:

- 14,951 public Freebase MIDs and names from the FB15k-237 name subset;
- 10,656 normalized GrailQA ontology types;
- 13,747 relations and 5,531 scalar properties;
- 9,908 directed reverse-property entries;
- the normalized SCC-condensed ontology with hash
  `8bd4f19503d3a61a89831da1d040afea93fae1f64446e0ffb206b510bb69c10b`.

The catalog hash is
`b547bf391a2dadf6c5affd205689da325bd4bce31b179b3d0a1f3c6bc4c4d416`.
Its manifest records source revisions, raw hashes, licenses, construction
command, file hashes, and counts. The entity source is deliberately a limited
public subset, not a complete Freebase alias catalog; retrieval recall must be
reported rather than assumed.

## Isolation Boundary

Inference reads `inference_questions.jsonl`, the public catalog, normalized
ontology, deterministic retrieval output, and the frozen M12-B ModelBundle.
The inference projection contains only question ID, text, split, and source ID.
It prevents the runner from opening a gold-bearing question row and merely
discarding its fields.

Before every provider call, a recursive fail-closed audit rejects gold forms,
answers, entity/relation annotations, reference interpretations, canonical
plans, `Q(u)`, `A(u)`, and other evaluation-only fields. Only after all selected
questions have an inference state does the evaluation stage open reference
interpretations and workload statistics. Tests deliberately inject each
forbidden category.

## Retrieval And Generation

Retrieval is deterministic lexical ranking over normalized public labels and
aliases. Its only semantic input is question text. Every row persists candidate
IDs, labels, scores, ranks, retrieval configuration, catalog hash, and question
hash. Post-inference evaluation computes entity, relation, and type Recall@1,
@5, @10, and @20.

The existing M12-B prompt and Qwen provider are unchanged. The frozen model is
`qwen3-max-2026-01-23`, temperature 0, top-p 1, candidate cap 3, no supported
seed, and at most one repair. Because the M12 candidate cap supersedes larger
requested values, the frozen M sensitivity grid is `{1,3}` rather than
`{1,3,5,10}`. One generated candidate set is reused for all six epsilon values.

## Deterministic Evaluation

Candidates pass the existing structured parser, PathPatternQuery type checker,
lowering validator, grounding checks, and unchanged directional ontology-hop
`c_sem`. Ranking uses `(c_sem, -confidence, structural_hash, candidate_id)`;
it does not modify M11 or Nash ranking.

Reference support is exact canonical PathPatternQuery structural equality after
removing variable names. Source/target orientation, relation direction,
selectors, restrictors, conditions, labels, properties, and path structure
remain significant. This is a conservative protocol, not a claim of general
graph-query semantic equivalence. References are unavailable before generation.

The first-failure taxonomy is frozen as retrieval miss, generation miss,
malformed output, type-check failure, entity-grounding failure,
relation-grounding failure, semantic-bound rejection, ranking failure, and
equivalence failure.

## Frozen Spec And Outputs

The immutable spec is
`experiments/specs/grailqa_semantic_pilot_v1.json`:

- file SHA-256:
  `736237ec3293a1b3a86e94e7f2592b36179a6edf97635e07c306ba4c91a9ca48`;
- canonical freeze hash:
  `5aeb1813813ca0c0835e30fa9c92644cf51a25b14480b6aa8b3d7e6938304e28`;
- pilot bundle hash:
  `dd27f7fecdb226bef89beb50339932793bd5ffe1b987e1ce4144f6391caacd72`.

Every run records source/environment/readiness identity, sanitized requests and
responses, validation, semantic scores, rankings, failures, JSON and CSV
metrics, progress, and a human-readable result summary. Per-query state is
written atomically. Resume skips successful provider calls and deterministic
terminal misses, and retries provider failures only.

Because generated dataset bodies are excluded from Git, the server bootstrap
is `scripts/server/fetch_grailqa_m13d_artifacts.sh`. On experiment servers it
automatically uses `/home/<user>/xgap-data` as a stable symlink to
`/data/<user>/xgap-artifacts`, keeping the large cache, unpacked benchmark, and
temporary build products off the home filesystem. It downloads the official
GrailQA v1.0 archive, the five ontology files at the frozen official revision,
and the FB15k-237 MID-name file at its frozen revision. Every source file is
SHA-256 checked. The script rebuilds the v2 audit prerequisite, pilot, and
catalog in a temporary cache, checks the built artifact hashes against the
immutable spec, then installs them atomically. It is idempotent and supports
`--verify-only` and an explicit `--force` rebuild.

## Local Orchestration Validation

The deterministic fake provider processed all 150 frozen IDs. It completed
150 requests, produced 450 parsed candidates, used no repairs, accounted for
all `Q=13/19/25` cases (83/56/11), and wrote every required output. This run is
marked `orchestration_only_no_accuracy_claim`; its retrieval and accuracy
values are not model-performance results. No full live Qwen run was performed
locally.
