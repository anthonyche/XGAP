"""Offline XGAP-only mode publication; reuse facts, prompts, catalog and weights."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_records import write_once
from xgap.planning.runtime_estimator import FrozenRuntimeEstimator


def derive_refined_modes_profile(*, parent_path, parent_sha256, output,
                                rows_per_relation, max_quality_deficit):
    parent=FrozenOneShotProfile.load(parent_path,expected_sha256=parent_sha256)
    doc,model,_,_,_,_,modes=parent.materialize()
    if isinstance(model,FrozenRuntimeEstimator):
        raise ValueError('Refined retrieval modes require the frozen work estimator')
    if 'mode_refinement' in doc['offline']:
        raise ValueError('Refuse to republish an already refined mode profile')
    policies={
        'precision':replace(modes['precision'][0],grounding_ranking='canonical_context_v1',
                            max_quality_deficit=max_quality_deficit),
        'performance':replace(modes['performance'][0],retrieval_rows_per_relation=rows_per_relation,
                              retrieval_scope='bind_after_anchor_v1')}
    for name in ('catalog','estimator'):
        doc[name]['path']=str((parent.root/doc[name]['path']).resolve())
    for source in doc['sources'].values():
        if 'equality_key_bounds' in source:
            pin=source['equality_key_bounds'];pin['path']=str((parent.root/pin['path']).resolve())
    for name,mode in doc['modes'].items():
        mode['policy']=asdict(policies[name])
        prompt=mode['provider']['prompt'];prompt['path']=str((parent.root/prompt['path']).resolve())
    doc['profile_id']+=':refined-modes-v1'
    doc['offline']['mode_refinement']={
        'parent':{'path':str(Path(parent_path).resolve()),'sha256':parent_sha256},
        'scope':'XGAP mode controls only; baseline comparisons must retain the parent frontend configuration',
        'rows_per_relation':rows_per_relation,'max_quality_deficit':max_quality_deficit,
        'query_reads':0,'answer_reads':0,'backend_calls':0,'model_calls':0,'fit_calls':0,'catalog_builds':0,
        'weights_changed':False,'formal_campaign_release':False}
    output=Path(output).resolve()
    FrozenOneShotProfile(output.parent,'unpublished',json.dumps(doc)).materialize()
    return write_once(output,doc)
