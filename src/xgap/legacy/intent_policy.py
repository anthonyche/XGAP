"""Opt-in terminal-first controller for the finite intent-family contract.

A bounded greedy clarification fallback, not globally optimal AND/OR search.
Only the realized information action calls the oracle; only a certified
candidate reaches physical preparation; final execution is attempted once.
"""
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import math
import time

from xgap.agent.intent_certificate import canonical, fingerprint, fraction_view
from xgap.tools.contracts import ToolContext, ToolEffect, ToolResult, ToolSpec, ToolStatus


@dataclass(frozen=True)
class FamilyUserTool:
    """Private selected intent, with public family/slot-scoped answers.

    Unlike the older full-intent oracle, a slot request needs no hidden query
    hash. Returning that hash would reveal which public candidate was selected.
    """
    family: object
    response_path: Path
    expected_sha256: str
    name: str = 'user.finite_intent'

    @property
    def spec(self):
        return ToolSpec(self.name, 'Ask the private user one declared intent coordinate',
            {'type':'object', 'required':['family_sha256','question_sha256','slot'],
             'properties':{'family_sha256':{'const':self.family.identity},
                'question_sha256':{'type':'string'},'slot':{'enum':[s.name for s in self.family.slots]}},
             'additionalProperties':False}, 'scoped_family_intent', ToolEffect.READ_ONLY)

    def invoke(self, arguments, context):
        at = time.perf_counter()
        try:
            if set(arguments) != {'family_sha256', 'question_sha256', 'slot'}:
                raise ValueError('Family user accepts only a scoped slot question')
            if arguments['family_sha256'] != self.family.identity:
                raise ValueError('Question belongs to another intent family or source snapshot')
            with self.response_path.open('rb') as stream:
                raw = stream.read(65537)
            if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != self.expected_sha256:
                raise ValueError('Private intent size/hash mismatch')
            data = json.loads(raw)
            if (set(data) != {'schema_version', 'family_sha256', 'question_sha256', 'candidate_id'} or
                    data['schema_version'] != 'xgap-private-family-intent-v1' or
                    any(data[k] != arguments[k] for k in ('family_sha256', 'question_sha256'))):
                raise ValueError('Private intent schema or question identity mismatch')
            i = next(i for i, c in enumerate(self.family.candidates) if c.candidate_id == data['candidate_id'])
            j = next(j for j, s in enumerate(self.family.slots) if s.name == arguments['slot'])
            result = ToolResult.success(self.name, {**arguments, 'answer': json.loads(self.family.values[i][j])})
        except (OSError, ValueError, KeyError, TypeError, StopIteration) as error:
            result = ToolResult.error_result(self.name, str(error) or 'Intent or slot is outside the declared family')
        return ToolResult(result.tool_name, result.status, result.value, result.error,
            metrics={'clarification_calls': 1, 'model_calls': 0, 'tokens': 0, 'remote_calls': 0,
                'elapsed_ms': (time.perf_counter()-at)*1000})


def choose_slot(family, remaining, observations):
    """Minimize largest outcome bucket; then prefer hard slots, then fixed order.

    Every selected question has at least two possible values. Every truthful
    branch removes at least one candidate; no execution-time probe is involved.
    """
    seen = {i for i, _ in observations}; options = []
    for j, slot in enumerate(family.slots):
        counts = Counter(family.values[i][j] for i in remaining)
        if j not in seen and len(counts) > 1:
            options.append((max(counts.values()), not slot.hard, j))
    return None if not options else min(options)[2]


def run_intent_policy(question, contract, oracle, *, prepare, execute, max_clarifications=32,
                      max_prepare_attempts=64, candidate_rank=None, on_observation=None):
    """Callbacks prepare/execute are the existing compiler/runtime boundary.

    Candidate rank is a frozen ordinal estimate, not an intent posterior. Both
    modes share it. There are no candidate executions or automatic retries.
    A semantic certificate alone does not assert backend executability or a
    precomputed strong continuation for every possible execution failure.
    """
    if type(max_clarifications) is not int or not 0 <= max_clarifications <= 32:
        raise ValueError('Clarification budget must lie in 0..32')
    if type(max_prepare_attempts) is not int or not 1 <= max_prepare_attempts <= 64:
        raise ValueError('Physical preparation attempts must lie in 1..64')
    family = contract.family
    rank = ({c.candidate_id: i for i, c in enumerate(family.candidates)}
        if candidate_rank is None else dict(candidate_rank))
    if set(rank) != {c.candidate_id for c in family.candidates} or any(
            type(v) not in (int, float) or not math.isfinite(v) for v in rank.values()):
        raise ValueError('A finite frozen ordinal rank must cover exactly the public candidates')
    started = time.perf_counter(); observations = (); failed_preparations = set()
    r = dict(schema_version='xgap-terminal-first-family-v1', success=False, status='preparing',
        family_sha256=family.identity, source_snapshot=family.source_snapshot, mode=contract.mode,
        epsilon=fraction_view(contract.epsilon), terminal_certificate=None, answer_rows=None,
        clarification_calls=0, model_calls=0, tokens=0, acquisition_remote_calls=0,
        oracle_processing_ms=0.0, clarification_wall_ms=0.0, certificate_ms=0.0,
        information_selection_ms=0.0, physical_preparation_ms=0.0, execution_ms=0.0,
        physical_prepare_attempts=0, final_plan_executions=0, expanded_states=0,
        ledger=[], prefixes=[], preparation_failures=[], root_gap=None,
        user_intent_verified=False, answer_quality_verified=False,
        strong_plan_verified=False, strong_scope='semantic termination conditional on closed family and truthful oracle; '
            'no precomputed physical continuations',
        acquisition_policy='bounded minimax-partition greedy; no approximation-ratio claim')
    checks_before, hits_before = contract.checks, contract.cache_hits
    try:
        # Precompute metric only, never physical plans. This cost is retained in
        # online certificate time here, not silently treated as a free catalog.
        at = time.perf_counter(); family.distances
        r['certificate_ms'] += (time.perf_counter()-at)*1000
        for _ in range(min(max_clarifications, len(family.slots)) + 1):
            remaining = family.consistent(observations); r['expanded_states'] += 1
            prefix = dict(index=len(observations), remaining_intents=len(remaining), checks=[])
            r['prefixes'].append(prefix)
            ordered = sorted(remaining, key=lambda i: (rank[family.candidates[i].candidate_id], i))
            for i in ordered:
                at = time.perf_counter(); certificate = contract.check(i, observations)
                r['certificate_ms'] += (time.perf_counter()-at)*1000
                prefix['checks'].append(certificate)
                if not certificate['eligible'] or i in failed_preparations:
                    continue
                if r['physical_prepare_attempts'] >= max_prepare_attempts:
                    r['status'] = 'physical_preparation_budget'; return r
                r['physical_prepare_attempts'] += 1; at = time.perf_counter()
                try:
                    plan = prepare(family.candidates[i], certificate)
                    if plan is None:
                        raise ValueError('Physical preparation did not return an executable plan')
                except Exception as error:
                    failed_preparations.add(i)
                    r['preparation_failures'].append(dict(candidate_id=family.candidates[i].candidate_id,
                        error_type=type(error).__name__, error=str(error)))
                    continue
                finally:
                    r['physical_preparation_ms'] += (time.perf_counter()-at)*1000
                r['terminal_certificate'] = certificate
                r['user_intent_verified'] = certificate['upper_bound']['numerator'] == 0
                r['final_plan_executions'] = 1; at = time.perf_counter()
                try:
                    result = execute(plan)
                finally:
                    r['execution_ms'] = (time.perf_counter()-at)*1000
                r['execution'] = result
                r.update(success=bool(result['success']), status='answered' if result['success'] else 'execution_failed',
                    answer_rows=result.get('answer_rows'))
                return r
            if family.coverage_basis is None:
                r['status'] = 'unknown_coverage'; return r
            # Terminal checked BEFORE the budget: a last permitted reply can
            # enable execution without paying for another acquisition action.
            if len(observations) >= max_clarifications:
                r['status'] = 'clarification_budget'; return r
            at = time.perf_counter(); j = choose_slot(family, remaining, observations)
            r['information_selection_ms'] += (time.perf_counter()-at)*1000
            if j is None:
                r['status'] = 'no_executable_terminal'; return r
            arguments = dict(family_sha256=family.identity, question_sha256=fingerprint(question), slot=family.slots[j].name)
            at = time.perf_counter(); r['clarification_calls'] += 1
            try:
                result = oracle.invoke(arguments, ToolContext('finite-intent', len(observations), str(len(observations))))
            finally:
                r['clarification_wall_ms'] += (time.perf_counter()-at)*1000
            record = dict(request=arguments, response=result.to_dict(),
                category='required_for_execution' if family.slots[j].hard else 'required_for_exactness')
            r['ledger'].append(record)
            r['oracle_processing_ms'] += result.metrics.get('elapsed_ms', 0)
            r['model_calls'] += result.metrics.get('model_calls', 0)
            r['tokens'] += result.metrics.get('tokens', 0)
            r['acquisition_remote_calls'] += result.metrics.get('remote_calls', 0)
            if on_observation is not None:
                on_observation(record)
            if result.status is not ToolStatus.SUCCESS:
                r['status'] = 'oracle_failed'; return r
            reply = result.value
            if not isinstance(reply, dict) or set(reply) != {*arguments, 'answer'} or any(reply[k] != v for k, v in arguments.items()):
                raise ValueError('Oracle response scope, question or snapshot mismatch')
            observations = (*observations, (j, canonical(reply['answer'])))
            family.consistent(observations)  # contradiction fails closed
        r['status'] = 'state_budget'; return r
    except Exception as error:
        r.update(status='failed', error_type=type(error).__name__, error=str(error))
        return r
    finally:
        r['certificate_checks'] = contract.checks - checks_before
        r['certificate_cache_hits'] = contract.cache_hits - hits_before
        r['end_to_end_ms'] = (time.perf_counter()-started)*1000
