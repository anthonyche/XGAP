"""Polynomial physical domain for frozen-estimate one-shot selection.

Admit local source alternatives, then generate a feasible baseline plus each
single-source deviation. For each placement, generate at most 2+2J legal strategy
DAGs. This explicit neighborhood is not the full Cartesian physical space.
Opt-in progressive binding adds at most one candidate per placement.
No backend, observation collector, or training action is invoked here.
"""

from dataclasses import replace
import hashlib
import json
import time

from xgap.compilers.errors import CompilerError
from xgap.runtime.physical_strategies import prepare_physical_strategies, strategy_features
from xgap.runtime.anchor_reduction import anchor_binding_slot
from xgap.runtime.semantic_compiler import compile_semantic_source
from xgap.runtime.semantic_placement import _admit_expansion
from xgap.runtime.retrieval_budget import apply_retrieval_budget
from xgap.runtime.shared_native_reads import share_full_native_reads
from xgap.runtime.source_row_filters import prefilter_source_rows
from xgap.semantic.program import SemanticOperatorKind as S, SemanticProgramError


def prepare_one_shot_domain(program, *, operator_sources, sources, backends, policy, progressive_bindings=False,
                            shared_native_reads=False,source_row_prefilters=False,planning_checkpoint=None):
    started = time.perf_counter()
    if planning_checkpoint is not None:planning_checkpoint()
    if any(type(v) is not bool for v in (progressive_bindings,shared_native_reads,source_row_prefilters)):
        raise ValueError('Physical profile flags must be boolean')
    if program.holes or len(program.operators) > policy.max_operators:
        raise SemanticProgramError("One-shot planning requires a bounded resolved program")
    _admit_expansion(program)
    operations = sorted((op for op in program.operators if op.kind in (S.MATCH, S.TRAVERSE)),
                        key=lambda op: op.operator_id)
    if set(operator_sources) != {op.operator_id for op in operations}:
        raise SemanticProgramError("Sources must cover every Match/Traverse exactly")
    domains, rejected, versions, identities = {}, [], {}, {}
    declared_count = 0
    for op in operations:
        source = sources.get(operator_sources[op.operator_id])
        if source is None or source.source_id != operator_sources[op.operator_id]:
            raise SemanticProgramError("Unknown logical source")
        declared_count += len(source.replica_backend_ids)
        if declared_count > policy.max_local_options:
            raise SemanticProgramError("Local-option budget exceeded before candidate expansion")
        if any(b not in backends or backends[b].backend_id != b for b in source.replica_backend_ids):
            raise SemanticProgramError("Each source replica needs a matching backend")
        if len({backends[b].resource_namespace for b in source.replica_backend_ids}) != 1:
            raise SemanticProgramError("Equivalent replicas must share their identity namespace")
        choices, schemas = [], set()
        for backend_id in sorted(source.replica_backend_ids):
            if planning_checkpoint is not None:planning_checkpoint()
            identity = {"source_id": source.source_id, "snapshot_version": source.snapshot_version}
            if backend_id in identities and identities[backend_id] != identity:
                raise SemanticProgramError("One-shot statistics require one snapshot version per backend")
            versions[backend_id] = source.snapshot_version
            identities[backend_id] = identity
            try:
                fragment = compile_semantic_source(op, backends[backend_id])
                schemas.add(fragment.schema)
                choices.append((backend_id, fragment.remote_calls))
            except (ValueError, CompilerError) as error:
                rejected.append({"operator_id": op.operator_id, "backend_id": backend_id,
                                 "status": "unsupported_local_option", "reason": str(error)})
        if not choices or len(schemas) != 1:
            raise SemanticProgramError("No schema-consistent local backend alternatives")
        domains[op.operator_id] = choices
    baseline = {op: min(choices, key=lambda item: (item[1], item[0]))[0]
                for op, choices in domains.items()}
    minimum_calls = sum(min(count for _, count in choices) for choices in domains.values())
    if minimum_calls > policy.max_remote_calls:
        raise SemanticProgramError("No source placement fits the final execution-call budget")
    placements = [baseline]
    for op, choices in domains.items():
        for backend_id, count in choices:
            if backend_id == baseline[op]:
                continue
            if minimum_calls - min(c for _, c in choices) + count <= policy.max_remote_calls:
                placements.append({**baseline, op: backend_id})
    join_count = sum(op.kind is S.JOIN for op in program.operators)
    anchor_slots = anchor_binding_slot(program)
    progressive_slots = int(progressive_bindings and bool(join_count))
    construction_bound = len(placements) * (1 + 2 * join_count + anchor_slots + progressive_slots)
    # Reject an over-budget domain before construction instead of silently
    # truncating it and misreporting exact selection over the promised domain.
    if construction_bound > policy.max_physical_candidates:
        raise SemanticProgramError("Declared physical domain exceeds candidate-work budget")
    candidates = []
    equality_bounds = {op: sources[source_id].equality_key_bounds
                       for op, source_id in operator_sources.items()
                       if sources[source_id].equality_key_bounds is not None}
    for index, placement in enumerate(placements):
        if planning_checkpoint is not None:planning_checkpoint()
        try:
            space = prepare_physical_strategies(program, source_bindings=placement,
                backends=backends, max_remote_calls=policy.max_remote_calls,
                max_parallelism=policy.max_parallelism, max_bindings=policy.max_bindings,
                max_binding_bytes=policy.max_binding_bytes,
                operator_equality_bounds=equality_bounds, progressive_bindings=progressive_bindings,
                planning_checkpoint=planning_checkpoint)
        except (ValueError, CompilerError) as error:
            rejected.append({"source_bindings": placement, "status": "unsupported_placement",
                             "reason": str(error)})
            continue
        for candidate in space.candidates:
            if planning_checkpoint is not None:planning_checkpoint()
            if policy.retrieval_rows_per_relation is not None:
                budgeted = apply_retrieval_budget(candidate.plan, program, policy.retrieval_rows_per_relation,
                                                 scope=policy.retrieval_scope)
                # Different budgeted physical orders can observe different
                # subsets. Never reuse the complete-program equivalence claim.
                candidate = replace(candidate, plan=budgeted, features=strategy_features(budgeted,program),
                                    semantic_equivalence_key=budgeted.metadata["semantic_equivalence_key"])
            encoded = json.dumps(candidate.plan.to_dict(), sort_keys=True, separators=(",", ":"))
            suffix = hashlib.sha256(encoded.encode()).hexdigest()[:20]
            used = {n.parameters["backend_id"] for n in candidate.plan.nodes
                    if "backend_id" in n.parameters}
            plan = replace(candidate.plan, plan_id=f"oneshot:{suffix}",
                metadata={**candidate.plan.metadata, "source_bindings": placement,
                          "source_snapshot_versions": {b: versions[b] for b in sorted(used)},
                          "source_identities": {b: identities[b] for b in sorted(used)}})
            if source_row_prefilters:plan=prefilter_source_rows(program,plan)
            if shared_native_reads:
                plan=share_full_native_reads(plan)
            if shared_native_reads or source_row_prefilters:
                candidate=replace(candidate,features=strategy_features(plan,program))
            candidates.append(replace(candidate, plan=plan,
                                      strategy_id=f"placement-{index}/{candidate.strategy_id}"))
        for rejection in getattr(space, "rejected_strategies", ()):
            rejected.append({"source_bindings": placement, "strategy": rejection})
    if not candidates:
        raise SemanticProgramError("No executable physical strategy in the admitted domain")
    return tuple(candidates), {"algorithm": "single_source_neighborhood_bind_and_anchor_fanout_v2",
        "cartesian_expansion": False, "local_option_count": declared_count,
        "placement_count": len(placements), "construction_bound": construction_bound,
        "candidate_count": len(candidates), "rejected": rejected,
        "anchor_candidate_upper_bound_per_placement": anchor_slots,
        **({"progressive_candidate_upper_bound_per_placement":progressive_slots,
            "algorithm":"single_source_neighborhood_with_progressive_bind_v1"} if progressive_bindings else {}),
        "domain": "one-source neighborhood; coordinator, one join bind, or one deterministic anchor fanout"
                  + ('; one progressive bind composition' if progressive_bindings else ''),
        "global_physical_optimality": False,
        **({'shared_native_reads':'identical-complete-native-reads-v1'} if shared_native_reads else {}),
        **({'source_row_prefilters':'mandatory-source-row-prefilter-v1'} if source_row_prefilters else {}),
        "elapsed_ms": (time.perf_counter() - started) * 1000}
