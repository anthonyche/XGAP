"""Bind resolved semantic identifiers into executable meaning, preserving constraints."""

from dataclasses import dataclass, replace
import json
from typing import Any, Mapping

from xgap.semantic.program import SemanticGraphProgram, SemanticHoleKind as H, SemanticOperatorKind as S, SemanticProgramError, hard_constraints_sha256


@dataclass(frozen=True)
class SemanticBindingValue:
    kind: H
    value: Any
    identity_property: str = "id"

    def __post_init__(self):
        if not isinstance(self.kind, H):
            raise SemanticProgramError("Binding kind must be a SemanticHoleKind")
        if type(self.value) not in (str, int, float, bool):
            raise SemanticProgramError("Binding values must be finite JSON scalars")
        if self.kind is not H.CONSTRAINT and (not isinstance(self.value, str) or not self.value):
            raise SemanticProgramError("Entity/schema/source bindings require nonempty identifiers")
        json.dumps(self.value, allow_nan=False)


@dataclass(frozen=True)
class BoundSemanticQuery:
    program: SemanticGraphProgram
    operator_sources: Mapping[str, str]
    bindings: Mapping[str, Any]


def bind_semantic_query(program: SemanticGraphProgram, resolution: Mapping[str, Any], *,
        binding_values: Mapping[str, SemanticBindingValue], operator_sources: Mapping[str, Any]) -> BoundSemanticQuery:
    if resolution.get("program_id") != program.program_id or resolution.get("hard_constraints_sha256") != hard_constraints_sha256(program):
        raise SemanticProgramError("Resolution does not belong to this program and its hard constraints")
    if resolution.get("hard_constraints_preserved") is not True:
        raise SemanticProgramError("Resolution did not preserve hard constraints")
    candidates = {item["hole_id"]: item for item in resolution["candidate_sets"]}
    selected, trace, used = {}, {}, set()
    for hole in program.holes:
        item = candidates.get(hole.hole_id)
        if item is None:
            if hole.required:
                raise SemanticProgramError(f"Missing resolution for {hole.hole_id}")
            continue
        ids = item.get("candidate_ids", ())
        if len(ids) != 1 or (hole.kind is H.ENTITY and item.get("authoritative") is not True):
            raise SemanticProgramError("One binding is required; entity identity must be authoritative")
        binding = binding_values.get(ids[0])
        if binding is None or binding.kind is not hole.kind:
            raise SemanticProgramError(f"No compatible typed binding for {hole.hole_id}")
        selected[hole.hole_id] = binding
        trace[hole.hole_id] = {"candidate_id": ids[0], "kind": binding.kind.value,
            "value": binding.value, "sources": item.get("sources", []),
            "authoritative": item.get("authoritative", False)}

    def bind(value, *, kind=None, path=(), parent=None, source=False, conjunctive=True):
        if isinstance(value, Mapping):
            if "$hole" in value:
                if set(value) != {"$hole"} or value["$hole"] not in selected:
                    raise SemanticProgramError("Unknown or unbound semantic slot")
                hole_id = value["$hole"]
                binding = selected[hole_id]
                if source != (binding.kind is H.SOURCE):
                    raise SemanticProgramError("Source holes bind logical sources only")
                if binding.kind is H.ENTITY:
                    descriptor = (kind is S.MATCH and path == ("parameters", "node", "properties", binding.identity_property)) or (
                        kind is S.TRAVERSE and len(path) == 5 and path[:2] == ("parameters", "path_pattern")
                        and path[2] in ("source", "target") and path[3:] == ("properties", binding.identity_property))
                    identity_predicate = (path[-1:] == ("value",) and isinstance(parent, Mapping)
                        and parent.get("kind") == "property_equals" and parent.get("property") == binding.identity_property
                        and isinstance(parent.get("ref"), Mapping) and parent["ref"].get("kind") == "node"
                        and kind in (S.MATCH, S.TRAVERSE) and conjunctive
                        and (path[:1] == ("constraint",) or "condition" in path))
                    if not (descriptor or identity_predicate):
                        raise SemanticProgramError("Entity bindings must enforce node identity, not decorate a query")
                used.add(hole_id)
                return binding.value
            return {key: bind(child, kind=kind, path=(*path, key), parent=value, source=source,
                    conjunctive=conjunctive and value.get("kind") not in ("or", "not"))
                    for key, child in value.items()}
        if isinstance(value, (list, tuple)):
            return [bind(child, kind=kind, path=(*path, i), parent=value, source=source,
                         conjunctive=conjunctive) for i, child in enumerate(value)]
        return value

    operators = []
    for op in program.operators:
        parameters = bind(op.parameters, kind=op.kind, path=("parameters",))
        constraints = tuple(replace(c, predicate=bind(c.predicate, kind=op.kind, path=("constraint", c.constraint_id)))
                            if c.predicate is not None else c for c in op.constraints)
        operators.append(replace(op, parameters=parameters, constraints=constraints))
    sources = bind(operator_sources, source=True)
    if {h.hole_id for h in program.holes if h.required} - used:
        raise SemanticProgramError("A required resolution was not applied to executable meaning")
    bound = replace(program, operators=tuple(operators), holes=(), metadata={**program.metadata,
        "semantic_binding": {"original_hard_constraints_sha256": hard_constraints_sha256(program), "bindings": trace}})
    return BoundSemanticQuery(bound, sources, trace)
