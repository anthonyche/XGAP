"""Controlled Interpretation-to-execution gate on the unchanged tiny graph.

The semantic template and catalog are authored fixtures, not model output.
Gold rows are used only after the production goal loop has returned.
"""

import hashlib
import json
from pathlib import Path

from xgap.agent.semantic_execution import run_frozen_semantic_query
from xgap.experiments.toy_backbone import load_fixture
from xgap.experiments.toy_semantic import toy_backends
from xgap.backends.rdf_terms import RDF_TERMS_V1, RdfTerm
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.row_operations import _rdf_scalar
from xgap.runtime.semantic_planning import LogicalSource, enumerate_semantic_plans
from xgap.runtime.scheduler import FederatedScheduler
from xgap.semantic.binding import SemanticBindingValue
from xgap.semantic.program import SemanticGraphProgram, SemanticHoleKind
from xgap.tools import ToolRegistry, BackendInvokeTool, BackendPluginRegistry, CatalogBackendPlugin
from xgap.tools.artifact_resolution import (ArtifactCatalogProvider, ExplicitUserSelectionProvider,
    artifact_catalog_tool, explicit_user_clarification_tool)


FIXTURE = Path(__file__).resolve().parents[3] / "datasets/backbone_binding_v1"
BUNDLE_FIXTURE = Path(__file__).resolve().parents[3] / "datasets/backbone_binding_bundle_v1"


def load_binding_cases():
    return json.loads((FIXTURE / "cases.json").read_text())


def reference_artifact(case, backend):
    language = "cypher" if backend == "neo4j" else "sparql"
    return QueryArtifact(case["id"] + "-reference-" + backend, language,
        (FIXTURE / case["reference_target_queries"][backend]).read_text(), kind="native",
        parameters={"rdf_result_encoding": RDF_TERMS_V1} if backend == "fuseki" else {})


def reference_rows(result, backend):
    if backend != "fuseki":
        return list(result.rows)
    return [{key:(RdfTerm.from_binding(value).value if key in ("person", "edge")
            and RdfTerm.from_binding(value).kind == "uri" else _rdf_scalar(value))
             for key,value in row.items()} for row in result.rows]


def binding_values():
    return {key: SemanticBindingValue(SemanticHoleKind(raw["kind"]), raw["value"])
            for key, raw in json.loads((FIXTURE / "bindings.json").read_text()).items()}


def resolution_tools(case, *, include_clarification=True):
    registry = ToolRegistry()
    registry.register(artifact_catalog_tool(ArtifactCatalogProvider(FIXTURE / "catalog.json")))
    if include_clarification and case.get("explicit_user_selection"):
        registry.register(explicit_user_clarification_tool(ExplicitUserSelectionProvider(
            case["explicit_user_selection"], source_id="controlled-toy-user-selection")))
    return registry


def execute_binding_case(case, mapping, *, clients):
    graph, _, _ = load_fixture()
    version = hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest()
    sources = {"toy": LogicalSource("toy", version, ("neo4j", "fuseki"))}
    backends = toy_backends(mapping)
    reference = json.loads((BUNDLE_FIXTURE / "reference.json").read_text())
    clarification = (explicit_user_clarification_tool(ExplicitUserSelectionProvider(
        case["explicit_user_selection"], source_id="controlled-toy-user-selection"))
        if case.get("explicit_user_selection") else None)
    run = run_frozen_semantic_query(program=SemanticGraphProgram.from_dict(case["program"]),
        question=case["nl"], operator_sources=case["operator_sources"],
        catalog_root=BUNDLE_FIXTURE / reference["root"], catalog_hash=reference["bundle_hash"],
        sources=sources, backends=backends, backend_clients=clients, clarification_tool=clarification,
        max_candidates=4, max_observation_calls=4)
    actual = run["state"]["output"]["planning_run"]["execution"]["value"]["final_rows"] if run["success"] else None
    canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
    record = {"query_id": case["id"], "success": run["success"] and canonical(actual) == canonical(case["expected_rows"]),
            "actual_rows": actual, "agent_run": run, "live_llm": False, "paper_result": False,
            "candidate_checks": [], "validation_only_extra_remote_calls": 0,
            "interpretation_source": "hand-authored template and pinned frozen resolution bundle"}
    if not record["success"]:
        return record
    output = run["state"]["output"]
    space = enumerate_semantic_plans(SemanticGraphProgram.from_dict(output["bound_program"]),
        operator_sources=output["operator_sources"], sources=sources, backends=backends,
        max_candidates=4, max_observation_calls=4)
    plugins = BackendPluginRegistry()
    for name, catalog in space.observation_catalogs.items():
        plugins.register(CatalogBackendPlugin(name, clients[name], catalog))
    for candidate in space.candidates:
        if candidate.plan.plan_id == output["planning_run"]["selection"]["selected_plan_id"]:
            rows, success, calls = actual, True, 0
        else:
            result = FederatedScheduler(BackendInvokeTool(plugins)).execute(candidate.plan)
            rows, success, calls = list(result.final_rows), result.success, result.total_remote_calls
        matched = success and canonical(rows) == canonical(case["expected_rows"])
        record["candidate_checks"].append({"plan_id": candidate.plan.plan_id,
            "source_bindings": candidate.plan.metadata["source_bindings"], "actual_rows": rows,
            "success": matched, "additional_remote_calls": calls})
        record["validation_only_extra_remote_calls"] += calls
        if not matched:
            record["success"] = False
            break
    return record
