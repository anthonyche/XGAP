"""Fixed-denominator, evaluation-only entity scores and one controlled E1-A slice."""

from copy import deepcopy

import pytest

from xgap.experiments.entity_answer_evaluation import evaluate_entity_answer_records


NS = "http://rdf.freebase.com/ns/"
COSTS = ("end_to_end_ms", "model_calls", "input_tokens", "output_tokens", "backend_remote_calls")


def _references(*identifiers, label="Display label is not identity"):
    return [{"kind": "entity", "id": identifier, "label": label,
             "equivalence_key": "entity:" + identifier} for identifier in identifiers]


def _record(*identifiers, status="answered", **costs):
    record = {"schema_version": "xgap-grounded-entity-answer-v1", "selection_policy": "semantic_bound",
              "epsilon": 0.0, "success": status == "answered", "status": status,
              "end_to_end_ms": 10.0, "model_calls": 1, "input_tokens": 100,
              "output_tokens": 20, "backend_remote_calls": 2}
    if record["success"]:
        record.update(answers=[{"type": "uri", "value": NS + identifier} for identifier in identifiers],
                      answer_count=len(set(identifiers)))
    record.update(costs)
    return record


def _evaluate(ids, records, references):
    return evaluate_entity_answer_records(question_ids=ids, records=records, references=references,
                                         selection_policy="semantic_bound", epsilon=0.0)


def test_complete_mixed_population_scores_failures_and_empty_answers_without_dropping_rows():
    ids = ("correct", "overlap", "failed-empty", "legal-empty", "wrong")
    records = {
        "wrong": _record("m.other"),
        "legal-empty": _record(),
        "failed-empty": _record(status="execution_failed", backend_remote_calls=1),
        "overlap": _record("m.a", "m.b"),
        "correct": _record("m.a"),
    }
    references = {"correct": _references("m.a"), "overlap": _references("m.a", "m.c"),
                  "failed-empty": [], "legal-empty": [], "wrong": _references("m.a")}
    before = deepcopy((records, references))
    result = _evaluate(ids, records, references)

    assert result["question_count"] == result["terminal_count"] == 5
    assert result["evaluation_complete"] is True
    assert [row["question_id"] for row in result["rows"]] == list(ids)
    assert [(row["answer_em"], row["answer_f1"]) for row in result["rows"]] == [
        (1, 1), (0, 0.5), (0, 0), (1, 1), (0, 0),
    ]
    assert result["metrics"]["answer_em"] == pytest.approx(2 / 5)
    assert result["metrics"]["answer_f1"] == pytest.approx(0.5)
    assert result["metrics"]["execution_completion_rate"] == pytest.approx(4 / 5)
    assert result["failure_counts"] == {"execution_failed": 1}
    assert result["costs"]["backend_remote_calls"] == {
        "known_count": 5, "unknown_count": 0, "known_sum": 9, "total": 9,
    }
    assert result["costs"]["end_to_end_ms"]["total"] == 50
    assert result["paper_result"] is False
    assert (records, references) == before


def test_unrun_questions_and_unknown_tokens_keep_the_full_denominator_and_unknown_costs():
    ids = ("unrun", "failed", "answered")
    records = {
        "answered": _record("m.a", input_tokens=None, output_tokens=5),
        "failed": _record(status="inference_failed", end_to_end_ms=20,
                           output_tokens=None, backend_remote_calls=0),
    }
    references = {qid: _references("m.a") for qid in ids}
    result = _evaluate(ids, records, references)
    assert result["question_count"] == 3 and result["terminal_count"] == 2
    assert result["evaluation_complete"] is False
    assert result["metrics"]["answer_em"] is result["metrics"]["answer_f1"] is None
    assert result["metrics"]["execution_completion_rate"] == pytest.approx(1 / 3)
    unrun, failed, answered = result["rows"]
    assert unrun["status"] == "not_run" and unrun["execution_completed"] is False
    assert unrun["answer_em"] is unrun["answer_f1"] is None
    assert unrun["costs"] == dict.fromkeys(COSTS)
    assert (failed["answer_em"], failed["answer_f1"]) == (0, 0)
    assert answered["costs"]["input_tokens"] is None
    assert result["failure_counts"] == {"not_run": 1, "inference_failed": 1}
    assert result["costs"]["end_to_end_ms"] == {
        "known_count": 2, "unknown_count": 1, "known_sum": 30, "total": None,
    }
    assert result["costs"]["input_tokens"] == {
        "known_count": 1, "unknown_count": 2, "known_sum": 100, "total": None,
    }
    assert result["costs"]["output_tokens"] == {
        "known_count": 1, "unknown_count": 2, "known_sum": 5, "total": None,
    }
    assert all(value["total"] is None for value in result["costs"].values())


def test_scalar_reference_remains_unsupported_and_prevents_a_cohort_accuracy_claim():
    records = {"entity": _record("m.a"), "scalar": _record("42")}
    references = {"entity": _references("m.a"), "scalar": [
        {"kind": "scalar", "lexical_value": "42", "equivalence_key": "scalar:42"},
    ]}
    result = _evaluate(("entity", "scalar"), records, references)
    assert result["terminal_count"] == result["question_count"] == 2
    assert result["evaluation_complete"] is False
    assert result["reference_unsupported_count"] == 1
    assert result["rows"][0]["answer_em"] == 1
    scalar = result["rows"][1]
    assert scalar["status"] == "answered" and scalar["reference_supported"] is False
    assert scalar["answer_em"] is scalar["answer_f1"] is None
    assert result["metrics"]["answer_em"] is result["metrics"]["answer_f1"] is None
    assert result["metrics"]["execution_completion_rate"] == 1
    assert result["costs"]["model_calls"]["total"] == 2


@pytest.mark.parametrize("predicted,em", [("m.same", 1), ("m.same_suffix", 0)])
def test_entity_identity_ignores_display_labels_and_deduplicates_exact_iris(predicted, em):
    references = {"q": [*_references("m.same", label="One spelling"),
                         *_references("m.same", label="A different spelling")]}
    records = {"q": _record(predicted, predicted)}
    result = _evaluate(("q",), records, references)
    assert result["rows"][0]["reference_supported"] is True
    assert result["metrics"]["answer_em"] == result["metrics"]["answer_f1"] == em
    assert result["evaluation_complete"] is True
    assert records["q"]["answer_count"] == 1 and len(records["q"]["answers"]) == 2


@pytest.mark.parametrize("invalid", [
    "duplicate-id", "missing-reference", "extra-record", "old-schema", "mixed-policy", "mixed-epsilon",
])
def test_population_and_method_cell_must_match_exactly(invalid):
    ids = ("q1", "q2")
    records = {qid: _record("m.a") for qid in ids}
    references = {qid: _references("m.a") for qid in ids}
    if invalid == "duplicate-id":
        ids = ("q1", "q1", "q2")
    elif invalid == "missing-reference":
        del references["q2"]
    elif invalid == "extra-record":
        records["outside"] = _record("m.a")
    elif invalid == "old-schema":
        records["q2"]["schema_version"] = "m13d-query-state-v1"
    elif invalid == "mixed-policy":
        records["q2"]["selection_policy"] = "model_top1"
    else:
        records["q2"]["epsilon"] = 0.25
    with pytest.raises(ValueError):
        _evaluate(ids, records, references)


@pytest.mark.parametrize("invalid", [
    "literal-answer", "failed-with-answers", "success-status-conflict", "nonterminal-running",
    "request-question-mismatch", "prompt-question-mismatch",
])
def test_invalid_results_identity_or_terminal_claims_are_not_scored(invalid):
    record = _record("m.a")
    if invalid == "literal-answer":
        record["answers"] = [{"type": "literal", "value": "m.a"}]
    elif invalid == "failed-with-answers":
        record = _record(status="execution_failed")
        record["answers"] = []  # Even an empty claim cannot turn failure into an answer.
    elif invalid == "success-status-conflict":
        record["status"] = "execution_failed"
    elif invalid == "nonterminal-running":
        record = _record(status="running")
    else:
        record = _record(status="inference_failed")
        record["inference"] = None
        if invalid == "request-question-mismatch":
            record["request"] = {"metadata": {"task_id": "another-question"}}
        else:
            record["prompt_view"] = {"task_id": "another-question"}
    with pytest.raises(ValueError):
        _evaluate(("q",), {"q": record}, {"q": _references("m.a")})


def test_new_controlled_inference_execution_slice_scores_only_after_answers_are_sealed(tmp_path, monkeypatch):
    from test_inferred_entity_answers import _inputs, _provider, _runtime, _run

    case = _inputs()
    provider, runtime = _provider(tmp_path, monkeypatch, case.raw), _runtime()
    run = _run(case, provider, runtime)
    assert run["success"] and run["status"] == "answered", run
    assert run["answers"] == [{"type": "uri", "value": NS + "m.release"}]
    assert len(provider.calls) == 1 and len(runtime.calls) == 2
    sealed = deepcopy(run)
    # The reference is handwritten and constructed after the ordinary E1-A run;
    # it is never passed to its catalog, prompt, selector, compiler, or backend.
    qid = case.question["question_id"]
    reference = _references("m.release", label="Independent expected release")
    result = _evaluate((qid,), {qid: run}, {qid: reference})
    assert result["evaluation_complete"] is True
    assert result["metrics"] == {"answer_em": 1.0, "answer_f1": 1.0, "execution_completion_rate": 1.0}
    assert result["question_count"] == result["terminal_count"] == 1
    for field in COSTS:
        assert result["costs"][field] == {
            "known_count": 1, "unknown_count": 0, "known_sum": run[field], "total": run[field],
        }
    assert result["paper_result"] is False
    assert run == sealed
    assert len(provider.calls) == 1 and len(runtime.calls) == 2
