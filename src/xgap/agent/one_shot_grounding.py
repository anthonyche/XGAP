"""Bounded frozen-artifact grounding without interactive identity resolution.

Each hole receives one prediction under an explicit local ranking; combinations are
never materialized. A predicted binding remains explicitly non-authoritative.
No model, backend, preparation builder, retry or answer reference is consulted.
"""

from dataclasses import replace
import re
import time

from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.semantic.binding import BoundSemanticQuery, bind_semantic_query
from xgap.semantic import normalize_semantic_mention
from xgap.semantic.program import SemanticGraphProgram, SemanticHoleKind, SemanticProgramError, hard_constraints_sha256
from xgap.tools.contracts import ToolContext
from xgap.tools.resolution import ResolutionCandidateRequest, ResolutionProviderFailure


class OneShotGroundingError(ValueError):
    """Terminal local failure with every lookup already attempted retained."""

    def __init__(self, status, message, trace):
        super().__init__(message)
        self.status, self.trace = status, trace


def _contextual_entity_order(candidates, response, mention, question):
    """Lexical evidence on an already capped pool; never authority or coreference proof."""
    labels = {m["candidate_id"]: m.get("canonical_label")
              for m in response.metadata.get("matches", []) if isinstance(m, dict) and "candidate_id" in m}
    question, mention = normalize_semantic_mention(question), normalize_semantic_mention(mention)
    evidence = []
    for index, candidate in enumerate(candidates):
        raw = labels.get(candidate)
        label = normalize_semantic_mention(raw) if isinstance(raw, str) and raw.strip() else None
        exact = label is not None and label == mention
        contextual = label is not None and re.search(r"(?<!\w)" + re.escape(label) + r"(?!\w)", question) is not None
        evidence.append({"candidate_id": candidate, "canonical_label": raw,
            "exact_canonical_mention": exact, "canonical_label_in_question": contextual,
            "artifact_index": index})
    evidence.sort(key=lambda row: (-int(row["exact_canonical_mention"]),
                                  -int(row["canonical_label_in_question"]), row["artifact_index"]))
    return tuple(row["candidate_id"] for row in evidence), evidence


def ground_interpretation(program, operator_sources, bundle, question, *,
                          max_holes=16, max_candidates_per_hole=64, use_ontology=True,
                          ranking_policy="artifact_entry_order_v1"):
    """Return ``(BoundSemanticQuery, trace)`` or raise OneShotGroundingError.

    Catalog matches are visited in frozen artifact order, with an explicit cap.
    Ontology is optional and used only when catalog lookup finds no predicate or
    type. Its existing one-hop expansion still rejects over-cap responses.
    ``authoritative`` is preserved only when actually granted by the artifact;
    predicted choices never become authority, calibrated confidence, or a bound
    on answer accuracy. Optional *referenced* holes must still bind successfully.
    """
    started = time.perf_counter()
    trace = {"schema_version": "xgap-one-shot-grounding-v1", "success": False,
        "status": "grounding_invalid", "selection_policy": "predicted_catalog_choice",
        "ranking_policy": "artifact_entry_order_v1", "lookups": [], "lookup_count": 0,
        "catalog_lookup_count": 0, "ontology_lookup_count": 0, "candidate_sets": [],
        "approximation_reasons": [], "external_calls": 0, "model_calls": 0,
        "input_tokens": 0, "output_tokens": 0, "automatic_retries": 0,
        "quality_calibrated": False, "candidate_combinations_materialized": False}

    def lookup(kind, provider, request, context):
        row = {"kind": kind, "request": request.to_dict(), "status": "started"}
        trace["lookups"].append(row)
        trace["lookup_count"] += 1
        trace[kind + "_lookup_count"] += 1
        before = time.perf_counter()
        try:
            response = (provider.resolve_bounded(request, context) if kind == "catalog"
                        else provider.resolve(request, context))
            row.update(status="success", response=response.to_dict())
            return response
        except Exception as error:
            row.update(status="failed", error_type=type(error).__name__, error=str(error))
            if isinstance(error, ResolutionProviderFailure):
                row.update(failure_category=error.failure_category, metadata=dict(error.metadata))
            raise
        finally:
            row["elapsed_ms"] = (time.perf_counter() - before) * 1000

    try:
        if (not isinstance(program, SemanticGraphProgram) or not isinstance(bundle, FrozenResolutionBundle)
                or not isinstance(question, str) or not question.strip()):
            raise ValueError("Grounding requires a semantic program, frozen bundle and nonempty question")
        if (type(max_holes) is not int or not 1 <= max_holes <= 64
                or type(max_candidates_per_hole) is not int or not 1 <= max_candidates_per_hole <= 256
                or type(use_ontology) is not bool):
            raise ValueError("Grounding requires bounded integer hole/candidate limits and boolean ontology policy")
        if ranking_policy not in ("artifact_entry_order_v1", "canonical_context_v1"):
            raise ValueError("Unknown grounding ranking policy")
        if ranking_policy != "artifact_entry_order_v1":
            trace.update(schema_version="xgap-one-shot-grounding-v2", ranking_policy=ranking_policy)
        if len(program.holes) > max_holes:
            raise ValueError("Semantic program exceeds its grounding hole budget")
        trace.update(resolution_bundle=bundle.identity, max_holes=max_holes,
                     max_candidates_per_hole=max_candidates_per_hole, use_ontology=use_ontology)
        hard_hash = hard_constraints_sha256(program)
        for index, hole in enumerate(program.holes):
            request = ResolutionCandidateRequest(program.program_id, hole.hole_id, hole.kind,
                hole.mention, (), question, hard_hash, max_candidates_per_hole)
            context = ToolContext("one-shot-grounding:" + program.program_id, index,
                                  "ground:" + hole.hole_id)
            response = lookup("catalog", bundle.catalog, request, context)
            source_kind = "catalog"
            if (not response.candidate_ids and use_ontology and bundle.ontology is not None
                    and hole.kind in (SemanticHoleKind.PREDICATE, SemanticHoleKind.TYPE)):
                response = lookup("ontology", bundle.ontology, request, context)
                source_kind = "ontology"
            candidates = response.candidate_ids
            evidence = None
            if ranking_policy == "canonical_context_v1" and hole.kind is SemanticHoleKind.ENTITY:
                candidates, evidence = _contextual_entity_order(candidates, response, hole.mention, question)
            record = {"hole_id": hole.hole_id, "hole_kind": hole.kind.value,
                "mention": hole.mention, "candidate_ids": list(candidates),
                "selected_candidate_id": candidates[0] if candidates else None,
                "authoritative": response.authoritative, "source_id": response.source_id,
                "source_kind": source_kind, "truncated": response.metadata.get("candidate_set_truncated", False),
                "ignored_program_candidates": list(hole.candidates),
                "selection_policy": "artifact_authoritative_singleton" if response.authoritative else "predicted_catalog_choice"}
            if evidence is not None:
                record.update(ranking_evidence=evidence, ranking_policy=ranking_policy,
                    original_candidate_ids=list(response.candidate_ids), evidence_is_authority=False)
            trace["candidate_sets"].append(record)
            if not candidates:
                record["status"] = "unresolved"
                if hole.required:
                    raise ValueError("No frozen-artifact candidate for required hole " + hole.hole_id)
                continue
            record["status"] = "selected"
            if record["truncated"]:
                trace["approximation_reasons"].append({"hole_id": hole.hole_id, "reason": "candidate_pool_truncated"})
            if len(candidates) > 1 or record["truncated"]:
                trace["approximation_reasons"].append({"hole_id": hole.hole_id,
                    "reason": "ambiguous_contextual_prediction" if evidence is not None else "ambiguous_artifact_order_choice"})
            if hole.kind is SemanticHoleKind.ENTITY and not response.authoritative:
                trace["approximation_reasons"].append({"hole_id": hole.hole_id, "reason": "non_authoritative_entity_prediction"})
        selected = [{"hole_id": item["hole_id"], "candidate_ids": [item["selected_candidate_id"]],
                     "authoritative": item["authoritative"], "sources": [item["source_id"]],
                     "selection_policy": item["selection_policy"]}
                    for item in trace["candidate_sets"] if item["selected_candidate_id"] is not None]
        resolution = {"program_id": program.program_id, "hard_constraints_sha256": hard_hash,
                      "hard_constraints_preserved": True, "candidate_sets": selected}
        bound = bind_semantic_query(program, resolution, binding_values=bundle.bindings,
                                   operator_sources=operator_sources, allow_predicted_entities=True)
        bound = BoundSemanticQuery(replace(bound.program, metadata={**bound.program.metadata,
                                   "resolution_bundle": bundle.identity}), bound.operator_sources, bound.bindings)
        trace.update(success=True, status="grounded", bindings=dict(bound.bindings), resolution=resolution,
                     approximate=bool(trace["approximation_reasons"]),
                     elapsed_ms=(time.perf_counter() - started) * 1000)
        return bound, trace
    except Exception as error:
        trace.update(status="grounding_failed", error_type=type(error).__name__, error=str(error),
                     elapsed_ms=(time.perf_counter() - started) * 1000)
        raise OneShotGroundingError(trace["status"], str(error), trace) from error
