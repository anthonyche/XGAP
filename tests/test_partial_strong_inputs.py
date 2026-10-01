"""Derived-input scope and shared predicate binding; no dataset/model execution."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from test_practical_profile import FIXTURE, ROOT, no_network, sha
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.partial_strong_inputs import publish_partial_cohort, partial_template
from xgap.experiments.practical_profile import FrozenPracticalProfile
from xgap.semantic.binding import bind_semantic_query
from xgap.semantic.intake import DeterministicSemanticIntake, SemanticIntakeError
from xgap.semantic.program import SemanticGraphProgram, hard_constraints_sha256


def inputs(root,*,rdf=False):
    base=json.loads((FIXTURE/'profile.json').read_text())
    for k in ('catalog','estimator'):base[k]['path']=str((FIXTURE/base[k]['path']).resolve())
    mapping=None
    if rdf:
        base['estimator']=None;base['sources']={'toy':{**base['sources']['toy'],'replicas':['fuseki']}}
        base['backends']={'fuseki':base['backends']['fuseki']}
        semantic=base['backends']['fuseki']['semantic']
        mapping=write_once(root/'mapping.json',{k:semantic[k] for k in
            ('resource_namespace','identity_property','backend_mapping','rdf_edge_encoding','rdf_node_classes')})
    profile=write_once(root/'parent-profile.json',base)
    operators=[]
    for i in range(2):
        operators.append({'operator_id':f'edge{i}','kind':'match','input_ids':[],'input_kinds':[],
            'output_kind':'binding_set','parameters':{'edge':{'label':'KNOWS'},'entity_field':f'e{i}',
                'source':{'label':'Person','properties':{'id':'explicit-ID'}},'source_field':f'p{i}','target_field':f'q{i}'}})
    operators += [{'operator_id':'joined','kind':'join','input_ids':['edge0','edge1'],
        'input_kinds':['binding_set','binding_set'],'output_kind':'binding_set',
        'parameters':{'left_on':'q0','right_on':'p1'}},
        {'operator_id':'limited','kind':'order_limit','input_ids':['joined'],'input_kinds':['binding_set'],
        'output_kind':'binding_set','parameters':{'order_by':[{'field':'p0'}],'limit':3}}]
    program=SemanticGraphProgram.from_dict({'program_id':'authored-test','operators':operators,'roots':['limited']})
    rows=[]
    for i,split in enumerate(('development','estimator_training','evaluation')):
        request=write_once(root/f'request-{i}.json',{'schema_version':'xgap-practical-request-v1','question_id':str(i),
            'question':f'Return connections for explicit-ID, version {i}.','population':'original','exposure':split,
            'trusted_bindings':{},'predictions':{},'clarifications':{}})
        semantic=write_once(root/f'semantic-{i}.json',{'family':'controlled','program':program.to_dict(),
            'operator_sources':{'edge0':'toy','edge1':'toy'},'reference_sparql':'not a runtime input'})
        rows.append({'question_id':str(i),'family':'controlled','split':split,'request':request,'profile':profile,
            'authored_semantics_as_explicit_input':semantic,'reference':{'path':str(root/f'UNREAD-{i}.json'),'sha256':'0'*64}})
    cohort=write_once(root/'cohort.json',{'schema_version':'xgap-resolved-strong-cohort-v1','dataset':base['dataset'],
        'instance_count':3,'split_counts':{r['split']:1 for r in rows},'groups':rows})
    policy=json.loads((ROOT/'experiments/protocols/partial_strong_inputs_candidate_v1.json').read_text())
    policy['family_rules']={'controlled':{'predicate':'KNOWS','phrases':['connections']}}
    policy['candidate_ids']=['predicate:knows','predicate:follows']
    policy['model_provider']['prompt']['path']=str(FIXTURE/'prompt.txt')
    p=write_once(root/'policy.json',policy)
    return dict(cohort_path=cohort['path'],cohort_sha256=cohort['sha256'],policy_path=p['path'],policy_sha256=p['sha256'],output=root/'published',
        **({'rdf_mapping_path':mapping['path'],'rdf_mapping_sha256':mapping['sha256']} if rdf else {}))


@pytest.mark.parametrize('rdf',[False,True])
def test_publication_preserves_denominator_and_meaning_without_reading_answers(tmp_path,monkeypatch,rdf):
    args=inputs(tmp_path,rdf=rdf);original_open=Path.open
    def guarded(path,*a,**kw):
        if path.name.startswith('UNREAD'):pytest.fail('Query answers were read during publication')
        return original_open(path,*a,**kw)
    monkeypatch.setattr(Path,'open',guarded)
    p=publish_partial_cohort(**args);doc=json.loads(Path(p['path']).read_text())
    assert doc['instance_count']==3 and doc['catalog_admission_count']==1
    assert doc['model_calls']==doc['backend_calls']==doc['planning_runs']==doc['catalog_builds']==doc['fit_calls']==0
    assert not doc['reference_contents_read'] and not doc['formal_campaign_ready']
    for group in doc['groups']:
        assert group['changed_operator_ids']==['edge0','edge1']
        raw=json.loads(Path(group['request']['path']).read_text())
        before=json.loads(Path(group['original_request']['path']).read_text())
        assert all(raw[k]==before[k] for k in ('question','question_id','population','exposure'))
        assert raw['trusted_bindings']==raw['predictions']=={}
        assert set(raw['clarifications'])=={'relation-authority'}
        profile,cfg=FrozenPracticalProfile.load_materialized(group['profile']['path'],expected_sha256=group['profile']['sha256'])
        assert cfg[0]['modes']['exact']['actions']==cfg[0]['modes']['performance']['actions']
        q=profile.prepare(raw,request_sha256=group['request']['sha256'],request_root=tmp_path,mode='exact',materialized=cfg)
        assert q.options.initial_state.choices==() and len(q.program.holes)==1
        # One binding changes all declared occurrences, preserving ID/join/limit.
        for candidate,label in [('predicate:knows','KNOWS'),('predicate:follows','FOLLOWS')]:
            bound=bind_semantic_query(q.program,{'program_id':q.program.program_id,
                'hard_constraints_sha256':hard_constraints_sha256(q.program),'hard_constraints_preserved':True,
                'candidate_sets':[{'hole_id':'relation','candidate_ids':[candidate],'authoritative':True}]},
                binding_values=cfg[2].bindings,operator_sources=cfg[0]['operator_sources'])
            assert all(op.parameters['edge']['label']==label for op in bound.program.operators[:2])
            assert bound.program.operators[0].parameters['source']['properties']['id']=='explicit-ID'
            assert bound.program.operators[-1].parameters['limit']==3
        raw['question']=raw['question'].replace('explicit-ID','another-ID')
        with pytest.raises(SemanticIntakeError,match='Question differs'):
            profile.prepare(raw,request_sha256='0'*64,request_root=tmp_path,mode='performance',materialized=cfg)
    from xgap.experiments.practical_methods import PRACTICAL_METHODS,STRONG_METHODS
    assert all(json.loads(Path(p['path']).read_text())['methods']==list(PRACTICAL_METHODS if rdf else STRONG_METHODS) for p in doc['study_inputs'].values())


@pytest.mark.parametrize('change',['duplicate','dataset','predictions','target','prompt','source','dependencies'])
def test_changed_or_unsupported_candidate_inputs_fail_without_release_manifest(tmp_path,change):
    args=inputs(tmp_path);cohort=json.loads(Path(args['cohort_path']).read_text())
    if change=='duplicate':cohort['groups'][1]['question_id']='0'
    elif change=='dataset':cohort['dataset']['version']='other'
    elif change=='predictions':
        old=cohort['groups'][0]['request'];raw=json.loads(Path(old['path']).read_text());raw['predictions']={'relation':'predicate:knows'}
        cohort['groups'][0]['request']=write_once(tmp_path/'wrong-request.json',raw)
    elif change=='source':
        old=cohort['groups'][1]['authored_semantics_as_explicit_input'];raw=json.loads(Path(old['path']).read_text())
        raw['operator_sources']['edge0']='undeclared'
        cohort['groups'][1]['authored_semantics_as_explicit_input']=write_once(tmp_path/'wrong-source.json',raw)
    elif change=='dependencies':
        old=cohort['groups'][1]['profile'];raw=json.loads(Path(old['path']).read_text())
        raw['sources']['toy']['version']='different'
        cohort['groups'][1]['profile']=write_once(tmp_path/'wrong-profile.json',raw)
    elif change in ('target','prompt'):
        policy=json.loads(Path(args['policy_path']).read_text())
        if change=='target':policy['family_rules']['controlled']['predicate']='NOT_PRESENT'
        else:policy['model_provider']['prompt']['sha256']='0'*64
        p=write_once(tmp_path/'wrong-policy.json',policy);args.update(policy_path=p['path'],policy_sha256=p['sha256'])
    p=write_once(tmp_path/'changed-cohort.json',cohort);args.update(cohort_path=p['path'],cohort_sha256=p['sha256'])
    with pytest.raises(ValueError):publish_partial_cohort(**args)
    assert not (tmp_path/'published/manifest.json').exists()


def test_optional_question_pin_is_enforced_without_requiring_it_for_old_partial_templates():
    from test_resolved_strong_inputs import simple_program
    program=simple_program().to_dict();op=program['operators'][0]
    op['parameters']={'edge':{'label':'KNOWS'},'entity_field':'e','source_field':'a','target_field':'b'}
    original=deepcopy(program)
    template,_=partial_template(SemanticGraphProgram.from_dict(program),'connections version1',
        {'predicate':'KNOWS','phrases':['connections']},template_id='partial-pin')
    assert program==original
    with pytest.raises(SemanticIntakeError,match='Question differs'):
        DeterministicSemanticIntake(template).compile('connections version2')
    template['metadata']['trusted_question_sha256']='bad'
    with pytest.raises(SemanticIntakeError,match='pin the exact question'):
        DeterministicSemanticIntake(template)
    template['metadata'].pop('trusted_question_sha256')
    assert DeterministicSemanticIntake(template).compile('connections version2').program.holes
