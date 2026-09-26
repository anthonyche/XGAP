#!/usr/bin/env python3
"""Replay sealed internal NL entries under verified public source constraints.

This is an offline repair audit, never a new measurement or an accuracy result.
Private intent is read only after the existing cell is sealed; neither its AST
nor values are emitted or supplied to a model/compiler repair.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from audit_ch6_nl_failures import Pins, safe_error
from xgap.agent.intent_certificate import fingerprint
from xgap.experiments.compact_constraints_profile import build_public_compact_constraints
from xgap.semantic.compact_equivalence import canonicalize_compact_surface
from xgap.semantic.compact_identity import IDENTITY_VERSION, matching_candidates
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.intent_scope import ScopePolicy, construct_scope, upgrade_edge_type_domains


INTERNAL = {'xgap-unified-lookahead', 'xgap-unified-no-probe',
            'xgap-unified-shallow', 'xgap-unified-myopic'}


def replay_entry(core, scope, private, constraints):
    report = core['interpretation']
    schema = report['request']['context']['source_schema']
    constraints.validate_source_schema(schema)
    raw = report['provenance']['raw_compact_response']
    proposals = []; rejections = []
    for index, candidate in enumerate(raw['candidates'][:8]):
        try:
            query, _ = canonicalize_compact_surface(candidate['query'], schema)
            lower_compact_query(query, schema, version='v2', optimize=True)
            proposals.append(query)
        except (ValueError, KeyError, TypeError) as error:
            rejections.append(dict(index=index, error_type=type(error).__name__, error=safe_error(error)))
    result = dict(proposals_lowered=len(proposals), proposal_rejections=rejections,
                  current_scope_covered=False)
    if not proposals:
        return {**result, 'replay_status': 'proposal_still_rejected'}
    try:
        policy = upgrade_edge_type_domains(ScopePolicy.from_dict(scope))
        family = construct_scope(proposals, policy, 'post-seal-contract-replay-only')
        if private['language_version'] != family.language_version:
            raise ValueError('Private and proposed compact language versions differ')
        bare = matching_candidates(private['query'], family.candidates, version=family.language_version)
        proved = matching_candidates(private['query'], family.candidates, version=family.language_version,
                                     constraints=constraints)
        if len(proved) > 1:
            raise ValueError('Public equivalence has no unique authority match')
        result.update(scope_covered_without_public_constraints=len(bare) == 1,
            current_scope_covered=len(proved) == 1, diagnostic_family_size=len(family.candidates),
            replay_status='scope_covered' if len(proved) == 1 else 'scope_still_outside')
    except (ValueError, KeyError, TypeError) as error:
        result.update(replay_status='scope_replay_error', error_type=type(error).__name__, error=safe_error(error))
    return result


def audit(*, release, evidence_root, output, mappings=(), proof_mirrors=()):
    release_path = Path(release); raw = release_path.read_bytes(); document = json.loads(raw)
    reader = Pins(mappings); rows = []; profiles = []; seen = set()
    for unit in document['units']:
        manifest = reader.read(unit['manifest'])
        prepared = reader.read(manifest['prepared']); profile_pin = prepared['profile']
        profile = reader.read(profile_pin)
        contract = build_public_compact_constraints(profile,
            profile_root=Path(profile_pin['path']).parent, pin_mirrors=proof_mirrors)
        profiles.append(dict(unit_id=unit['unit_id'], prepared_sha256=manifest['prepared']['sha256'],
            profile_sha256=profile_pin['sha256'], public_constraints_sha256=contract.identity,
            public_constraints=contract.to_dict()))
        for cell in manifest['cells']:
            if cell['method'] not in INTERNAL:
                continue
            identity = (unit['unit_id'], cell['cell_id'])
            if identity in seen:
                raise ValueError('Duplicate sealed cell identity')
            seen.add(identity)
            terminals = list(Path(evidence_root).glob('**/units/'+unit['unit_id']+'/cells/'+cell['cell_id']+'/terminal.json'))
            if len(terminals) != 1:
                raise ValueError('Exactly one sealed terminal required per declared internal request')
            terminal = json.loads(terminals[0].read_text()); trial = reader.read(terminal['outcome'])
            if terminal['cell_id'] != cell['cell_id'] or trial['method'] != cell['method']:
                raise ValueError('Sealed request/method identity differs')
            for field in ('request', 'scope', 'oracle'):
                if trial[field+'_sha256'] != cell[field]['sha256']:
                    raise ValueError('Sealed entry pin differs from frozen manifest')
            core = reader.read(trial['core']); request = reader.read(cell['request'])
            scope = reader.read(cell['scope']); private = reader.read(cell['oracle'])
            if (core['interpretation']['request']['question'] != request['question']
                    or private['question_sha256'] != fingerprint(request['question'])):
                raise ValueError('Sealed public/private question identity differs')
            row = dict(unit_id=unit['unit_id'], cell_id=cell['cell_id'], case_id=trial['question_id'],
                method=cell['method'], dataset=unit['dataset'], deployment=unit['deployment'],
                recorded_status=trial['status'], recorded_outcome_sha256=terminal['outcome']['sha256'],
                core_sha256=trial['core']['sha256'], public_constraints_sha256=contract.identity,
                **replay_entry(core, scope, private, contract))
            rows.append(row)
    statuses = Counter(row['recorded_status'] for row in rows)
    replay = Counter(row['replay_status'] for row in rows)
    answered = [row for row in rows if row['recorded_status'] == 'answered']
    newly = [row for row in rows if row['recorded_status'] != 'answered' and row['current_scope_covered']]
    result = dict(schema_version='xgap-post-seal-public-contract-replay-v1',
        release_sha256=hashlib.sha256(raw).hexdigest(), identity_version=IDENTITY_VERSION,
        internal_requests=len(rows), distinct_questions=len({row['case_id'] for row in rows}),
        recorded_statuses=dict(statuses), current_offline_replay=dict(replay),
        previously_answered_scope_retained=sum(row['current_scope_covered'] for row in answered),
        previously_answered_scope_regressions=sum(not row['current_scope_covered'] for row in answered),
        newly_scope_covered_requests=len(newly), newly_scope_covered_questions=len({row['case_id'] for row in newly}),
        profiles=profiles, rows=rows, private_access='Post-seal diagnostic only; no query or private values emitted',
        interpretation='Source-contract scope admission only; no planning, answer execution or new accuracy measurement',
        historical_results_changed=0, method_results_created=0, model_calls=0, backend_calls=0)
    root = Path(output); root.mkdir(parents=True, exist_ok=False)
    (root/'audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('release', 'evidence-root', 'output'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--pin-mirror', action='append', default=[], help='Original absolute prefix=mirror root; repeatable')
    parser.add_argument('--proof-mirror', action='append', default=[], help='Public source proof prefix=mirror; most specific wins')
    args = vars(parser.parse_args())
    args['mappings'] = [value.split('=', 1) for value in args.pop('pin_mirror')]
    args['proof_mirrors'] = [value.split('=', 1) for value in args.pop('proof_mirror')]
    result = audit(**args)
    print(json.dumps({k:result[k] for k in ('internal_requests', 'distinct_questions', 'recorded_statuses',
        'current_offline_replay', 'previously_answered_scope_retained', 'previously_answered_scope_regressions',
        'newly_scope_covered_requests', 'newly_scope_covered_questions', 'model_calls', 'backend_calls')}))
