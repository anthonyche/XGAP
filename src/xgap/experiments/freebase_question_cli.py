"""Explicit development CLI: question/catalog -> bounded provider -> native answer."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.experiments.bundles import ModelBundle
from xgap.experiments.freebase_candidate_compiler import ExecutionRequirements, FreebaseExecutionMapping
from xgap.experiments.freebase_question import QuestionBudget, answer_question
from xgap.experiments.grailqa_candidate_feedback import TYPED_GROUNDING_ONCE
from xgap.experiments.grailqa_candidate_grounding import SEMANTIC_GROUNDING_POLICY
from xgap.experiments.grailqa_catalog_v2 import GrailQAInferenceCatalogV2
from xgap.experiments.grailqa_guarded_provider import (
    GuardedSemanticPilotProvider, QueryEventJournal, _credential_value_for_payload_check,
)
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.llm.openai_compatible import redact_secrets
from xgap.llm.token_budget import ChatTokenBudgetGuard, LocalPinnedChatTokenizer


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, help="JSON with question, mapping, requirements and budgets")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--model-bundle", required=True)
    parser.add_argument("--tokenizer-snapshot", required=True)
    parser.add_argument("--tokenizer-revision", required=True)
    parser.add_argument("--context-limit", required=True, type=int)
    parser.add_argument("--neo4j-descriptor", required=True)
    parser.add_argument("--fuseki-descriptor", required=True)
    parser.add_argument("--output", required=True, help="New directory; existing runs are never reopened")
    parser.add_argument("--verify-baseline", action="store_true")
    parser.add_argument("--execute", action="store_true", help="Enable model and read-only backend calls")
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error("--execute is required for external model/backend calls")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    report = {"success": False, "status": "input_unavailable", "paper_result": False}
    credential = ""
    try:
        data = json.loads(Path(args.request).read_text())
        model = ModelBundle.load(args.model_bundle)
        base = build_openai_compatible_provider(model, response_parser=parse_normalized_planner_response)
        credential = _credential_value_for_payload_check(
            os.environ.get(base.config.api_key_env, ""), base.config.base_url+"/chat/completions")
        mapping = FreebaseExecutionMapping(**data["mapping"])
        requirements = ExecutionRequirements(**data["requirements"])
        budget = QuestionBudget(**data.get("budgets", {}))
        if model.config.candidate_count > budget.candidate_cap or model.config.max_repair_calls != 1:
            raise ValueError("This entry requires at most three candidates and one shared repair")
        counter = LocalPinnedChatTokenizer(args.tokenizer_snapshot, args.tokenizer_revision)
        guard = ChatTokenBudgetGuard(counter, input_limit=model.config.token_limits["input"],
            output_limit=model.config.token_limits["output"], context_limit=args.context_limit,
            expected_model=base.config.model)
        catalog = GrailQAInferenceCatalogV2.load(args.catalog)
        neo = Neo4jClient(BackendDescriptor.from_yaml(args.neo4j_descriptor))
        rdf = FusekiClient(BackendDescriptor.from_yaml(args.fuseki_descriptor))
        with QueryEventJournal(output/"provider-events.jsonl") as journal:
            def factory(qid):
                return GuardedSemanticPilotProvider(model, guard, journal, qid, base_provider=base,
                    candidate_repair_policy=TYPED_GROUNDING_ONCE, grounding_policy=SEMANTIC_GROUNDING_POLICY)
            report = answer_question(question_record=data["question"], catalog=catalog, provider_factory=factory,
                mapping=mapping, requirements=requirements, neo4j=neo, fuseki=rdf,
                budget=budget, verify_baseline=args.verify_baseline)
            report["tokenizer_identity"] = counter.identity
            report["model_bundle_hash"] = model.bundle_hash
            report["serving_tokenizer_parity_verified"] = False
    except Exception as error:
        report.update(error_type=type(error).__name__)
    encoded = json.dumps(redact_secrets(report), indent=2, sort_keys=True, allow_nan=False)
    if credential:
        encoded = encoded.replace(credential, "[REDACTED]")
    with (output/"result.json").open("x") as handle:
        handle.write(encoded+"\n")
    print(json.dumps({"status": report["status"], "success": report["success"], "result": str(output/"result.json")}))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
