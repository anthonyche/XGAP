"""Outcome-blind sampling frames for the two separately reported populations.

This module never opens a query, private intent, reference answer or run result.
The active frame reads only edge endpoints and ownership. It can contain empty
answers, and overlaps the all-ID frame; it is not a disjoint population partition.
"""
import random

from xgap.agent.intent_certificate import fingerprint
from xgap.experiments.chapter7_finbench_coverage import fold
from xgap.experiments.chapter7_finbench_families import TEMPLATES

STRATA = ('all_ids', 'active_anchors')
SEED = 'xgap-ch7-finbench-dual-frame-20260921-v1'


def _ids(values):
    values = tuple(sorted(str(v) for v in values))
    if len(values) != len(set(values)) or any(not v for v in values):
        raise ValueError('Unique nonempty source identifiers required')
    return values


def structural_frames(accounts, companies, transfers, company_by_account):
    """Account: outgoing transfer. Company: owns a transfer recipient.

    All source times and all property values qualify. Parallel edges have no
    additional weight; even self loops qualify (a later acyclic query may be empty).
    """
    account_ids, company_ids = _ids(accounts), _ids(companies)
    account_set, company_set = set(account_ids), set(company_ids)
    owners = {str(a): str(c) for a, c in company_by_account.items()}
    if len(owners) != len(company_by_account):
        raise ValueError('Ambiguous normalized ownership identifiers')
    if set(owners) - account_set or set(owners.values()) - company_set:
        raise ValueError('Ownership references absent source identifiers')
    outgoing, receiving_companies = set(), set()
    for edge in transfers:
        source, target = str(edge.from_id), str(edge.to_id)
        if source not in account_set or target not in account_set:
            raise ValueError('Transfer references absent account')
        outgoing.add(source)
        if target in owners:
            receiving_companies.add(owners[target])
    return {
        'all_ids': dict(account=account_ids, company=company_ids),
        'active_anchors': dict(account=tuple(sorted(outgoing)), company=tuple(sorted(receiving_companies))),
    }


def select_families(frames, *, per_shape, seed=SEED, target_fold='formal'):
    """Uniform anchors without replacement within each frame, then window/intent.

    Account anchors are distinct across its two shapes within each frame. Frames
    use independent random streams: do not exclude the uniform selection from the
    active frame. Any cross-frame overlap retains the same family group ID.
    """
    if type(per_shape) is not int or not 1 <= per_shape <= 1000:
        raise ValueError('Bounded positive integer per-shape sample required')
    if target_fold not in ('pilot', 'formal') or not isinstance(seed, str) or not seed:
        raise ValueError('Explicit fold and nonempty seed required')
    if set(frames) != set(STRATA):
        raise ValueError('Both predeclared frames required')
    normalized = {}
    for stratum in STRATA:
        if set(frames[stratum]) != {'account', 'company'}:
            raise ValueError('Typed account and company frames required')
        normalized[stratum] = {kind: _ids(ids) for kind, ids in frames[stratum].items()}
    if any(set(normalized['active_anchors'][k]) - set(normalized['all_ids'][k]) for k in ('account','company')):
        raise ValueError('Active frame must be contained in all source identifiers')
    selected, evidence = [], []
    for stratum in STRATA:
        pools = {k: [a for a in ids if fold(k, a) == target_fold] for k, ids in normalized[stratum].items()}
        if len(pools['account']) < 2 * per_shape or len(pools['company']) < per_shape:
            raise ValueError('Insufficient independent anchors in '+stratum)
        rng = random.Random(fingerprint([seed, stratum, target_fold]))
        accounts = rng.sample(pools['account'], 2 * per_shape)
        companies = rng.sample(pools['company'], per_shape)
        evidence.append(dict(stratum=stratum, counts={k: len(v) for k,v in normalized[stratum].items()},
            source_frame_sha256=fingerprint(normalized[stratum]),
            eligible_fold_counts={k: len(v) for k,v in pools.items()},
            eligible_fold_sha256=fingerprint(pools)))
        for position, template in enumerate(TEMPLATES):
            kind = 'company' if position == 2 else 'account'
            anchors = companies if kind == 'company' else accounts[position*per_shape:(position+1)*per_shape]
            for anchor in anchors:
                selected.append(dict(index=len(selected), stratum=stratum, template=template,
                    anchor_type=kind, anchor=anchor,
                    family_group_id=fingerprint(['finbench-sf0.1', kind, anchor]),
                    window=rng.randrange(4), truth_index=rng.randrange(16)))
    return dict(schema_version='xgap-ch7-dual-frame-selection-v1', seed=seed, target_fold=target_fold,
        per_shape=per_shape, frames=evidence, selected=selected,
        samples_per_stratum=3*per_shape, total_case_records=len(selected),
        distinct_anchor_groups=len({s['family_group_id'] for s in selected}),
        overlap_anchor_groups=6*per_shape-len({s['family_group_id'] for s in selected}),
        answer_reads_at_selection=0, method_output_reads=0,
        reporting='separate population estimates; no pooled superiority estimate',
        unit='type-qualified anchor; shared across windows, intents, repeats and sampling frames')
