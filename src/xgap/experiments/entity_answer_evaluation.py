"""Evaluation-only entity identity scores over a fixed question population.

Invoke only after inference/execution is sealed. This module has no generation,
ranking, file loading or backend access and does not implement scalar equivalence.
"""

from collections import Counter
import math
from typing import Any, Mapping, Sequence

from xgap.backends.rdf_terms import RdfTerm, validate_iri
from xgap.runtime.answers import AnswerProjection, exact_answer_match


RUN_SCHEMA = "xgap-grounded-entity-answer-v1"
COST_FIELDS = ("end_to_end_ms", "model_calls", "input_tokens", "output_tokens", "backend_remote_calls")
TERMINAL_STATUSES = frozenset({"answered", "input_failed", "budget_exhausted", "inference_failed",
    "provider_contract_failed", "no_admissible_meaning", "selected_meaning_unavailable",
    "admission_failed", "execution_failed", "answer_invalid", "grounding_unavailable", "clarification_required"})


def _terms(bindings):
    if not isinstance(bindings, list):
        raise ValueError("A complete entity answer must be an explicit list")
    terms = AnswerProjection("answer").project_rows({"answer": item} for item in bindings)
    if any(term.kind != "uri" for term in terms):
        raise ValueError("This evaluation profile accepts entity IRIs only")
    return terms


def _reference(answers, namespace):
    if not isinstance(answers, list):
        raise ValueError("Normalized references must contain an answer list")
    entities = []
    supported = True
    for item in answers:
        if not isinstance(item, Mapping):
            raise ValueError("Malformed normalized reference")
        if item.get("kind") == "scalar":
            if (not isinstance(item.get("lexical_value"), str)
                    or item.get("equivalence_key") != "scalar:" + item["lexical_value"]):
                raise ValueError("Malformed normalized scalar reference")
            supported = False
        elif item.get("kind") == "entity":
            identifier = item.get("id")
            if (not isinstance(identifier, str) or not identifier
                    or item.get("equivalence_key") != "entity:" + identifier):
                raise ValueError("Malformed normalized entity reference")
            entities.append(RdfTerm("uri", namespace + identifier).to_binding())
        else:
            raise ValueError("Unknown normalized reference answer kind")
    return supported, _terms(entities)


def _costs(record):
    values = {}
    for key in COST_FIELDS:
        value = record.get(key)
        if value is not None:
            types = (int, float) if key == "end_to_end_ms" else (int,)
            if type(value) not in types or not math.isfinite(value) or value < 0:
                raise ValueError("Cost must be a nonnegative finite observation or explicit unknown")
        values[key] = value
    return values


def evaluate_entity_answer_records(*, question_ids: Sequence[str],
        records: Mapping[str, Mapping[str, Any]], references: Mapping[str, list],
        selection_policy: str, epsilon: float,
        namespace: str = "http://rdf.freebase.com/ns/") -> dict[str, Any]:
    """Score one method cell, retaining the entire population and unknown costs."""
    ids = tuple(question_ids)
    if (isinstance(question_ids, str) or not ids
            or any(not isinstance(qid, str) or not qid for qid in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("Question population must be explicit, nonempty and unique")
    if (set(references) != set(ids) or set(records) - set(ids)
            or any(not isinstance(record, Mapping) for record in records.values())):
        raise ValueError("References and records must respect the exact declared population")
    if (selection_policy not in {"semantic_bound", "model_top1"}
            or type(epsilon) not in (int, float) or not math.isfinite(epsilon)
            or not 0 <= epsilon <= 1):
        raise ValueError("Explicit selection policy and finite epsilon are required")
    validate_iri(namespace)
    if not namespace.endswith(("/", "#")):
        raise ValueError("Entity namespace must end with an explicit separator")
    rows, failures = [], Counter()
    for qid in ids:
        supported, expected = _reference(references[qid], namespace)
        record = records.get(qid)
        row = {"question_id": qid, "status": "not_run", "reference_supported": supported,
               "execution_completed": False, "answer_em": None, "answer_f1": None,
               "costs": {key: None for key in COST_FIELDS}}
        if record is not None:
            if (not isinstance(record, Mapping) or record.get("schema_version") != RUN_SCHEMA
                    or record.get("selection_policy") != selection_policy
                    or type(record.get("epsilon")) not in (int, float)
                    or record["epsilon"] != epsilon or type(record.get("success")) is not bool
                    or not isinstance(record.get("status"), str)
                    or record["status"] not in TERMINAL_STATUSES):
                raise ValueError("Execution record does not match this method cell")
            success = record["success"]
            if (success != (record["status"] == "answered")
                    or record["status"] == "not_run"
                    or (not success and ("answers" in record or "answer_count" in record))):
                raise ValueError("Execution status and complete-answer claims disagree")
            inference = record.get("inference")
            if (isinstance(inference, Mapping) and isinstance(inference.get("question"), Mapping)
                    and inference["question"].get("question_id") != qid):
                raise ValueError("Execution record belongs to a different question")
            request = record.get("request")
            metadata = request.get("metadata") if isinstance(request, Mapping) else None
            for identity in (metadata, record.get("prompt_view")):
                if isinstance(identity, Mapping) and "task_id" in identity and identity["task_id"] != qid:
                    raise ValueError("Retained request or prompt view belongs to a different question")
            row.update(status=record["status"], execution_completed=success, costs=_costs(record))
            actual = _terms(record.get("answers")) if success else ()
            if success and (type(record.get("answer_count")) is not int
                            or record["answer_count"] != len(actual)):
                raise ValueError("Declared answer count differs from its entity set")
            if supported:
                denominator = len(actual) + len(expected)
                overlap = len({t.identity for t in actual} & {t.identity for t in expected})
                row.update(answer_em=float(success and exact_answer_match(actual, expected)),
                           answer_f1=(2 * overlap / denominator if denominator else 1.0) if success else 0.0)
        if not row["execution_completed"]:
            failures[row["status"]] += 1
        rows.append(row)
    complete = len(records) == len(ids) and all(row["reference_supported"] for row in rows)
    costs = {}
    for key in COST_FIELDS:
        known = [row["costs"][key] for row in rows if row["costs"][key] is not None]
        costs[key] = {"known_count": len(known), "unknown_count": len(ids) - len(known),
                      "known_sum": sum(known), "total": sum(known) if len(known) == len(ids) else None}
    return {"schema_version": "xgap-entity-answer-evaluation-v1", "question_count": len(ids),
        "terminal_count": len(records), "evaluation_complete": complete,
        "selection_policy": selection_policy, "epsilon": epsilon, "namespace": namespace,
        "rows": rows, "failure_counts": dict(failures), "costs": costs,
        "reference_unsupported_count": sum(not row["reference_supported"] for row in rows),
        "metrics": {"answer_em": sum(row["answer_em"] for row in rows) / len(ids) if complete else None,
                    "answer_f1": sum(row["answer_f1"] for row in rows) / len(ids) if complete else None,
                    "execution_completion_rate": sum(row["execution_completed"] for row in rows) / len(ids)},
        "scoring_scope": "entity_IRI_set_identity_only", "denominator": "all_declared_questions",
        "temporal_gold_isolation_verified": False, "paper_result": False}
