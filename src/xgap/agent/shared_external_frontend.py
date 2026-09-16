"""Common frozen NL interpretation, quality-first choice, one global compilation."""
from dataclasses import replace
import time

from xgap.agent.one_shot_grounding import ground_interpretation
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.compilers.global_semantic_sparql import compile_global_program
from xgap.semantic.interpretation_candidates import interpret_candidate_question
from xgap.semantic.program import SemanticGraphProgram


def prepare_external_query(request,provider,*,policy,catalog_root,catalog_hash,sources,mapping,
                           information_profile='precision-k3-v1'):
    started=time.perf_counter()
    r={'schema_version':'xgap-shared-external-frontend-v1','success':False,'status':'preparing',
        'interpretation':None,'candidates':[],'selection':None,'artifact':None,
        'model_calls':0,'input_tokens':0,'output_tokens':0,'usage_complete':True,
        'backend_calls':0,'fit_calls':0,'probe_calls':0,'automatic_retries':0,'compilations':0,
        'catalog_load_ms':0.,'grounding_ms':0.,'selection_ms':0.,'compilation_ms':0.}
    def finish():
        r['frontend_ms']=(time.perf_counter()-started)*1000
        return r
    try:
        caps={'precision-k3-v1':3,'nl-conditional-strong-k1-v1':1}
        if information_profile not in caps:
            raise ValueError('Unknown frozen shared frontend information profile')
        if not isinstance(policy,OneShotPolicy) or policy.mode!='precision' or policy.candidate_cap!=caps[information_profile]:
            raise ValueError('Shared external frontend policy does not match its explicit frozen information profile')
        r['information_profile']=information_profile
        config=getattr(provider,'config',None)
        if config is not None and config.candidate_cap!=policy.candidate_cap:
            raise ValueError('Provider wire candidate bound differs')
        at=time.perf_counter()
        bundle=FrozenResolutionBundle.load(catalog_root,expected_bundle_hash=catalog_hash)
        r['catalog_load_ms']=(time.perf_counter()-at)*1000
        request=replace(request,context={**request.context,'one_shot_profile':policy.to_dict(),
            'runtime':{'resolution_bundle':bundle.identity,'sources':{name:{'version':s.snapshot_version,
                'replicas':list(s.replica_backend_ids)} for name,s in sources.items()}}})
        interpreted=interpret_candidate_question(request,provider,candidate_cap=policy.candidate_cap)
        r['interpretation']=interpreted
        r['usage_complete']=not interpreted.get('usage_unavailable',False)
        r['call_count_complete']=interpreted.get('external_call_count_complete',True)
        r['model_calls']=interpreted['external_calls'] if r['call_count_complete'] else None
        for key in ('input_tokens','output_tokens'):r[key]=interpreted[key] if r['usage_complete'] else None
        r['usage_known_lower_bounds']={k:interpreted[k] for k in ('external_calls','input_tokens','output_tokens')}
        if not interpreted['success']:
            r.update(status=interpreted['status'],error=interpreted['error']);return finish()
        choices=[]
        for candidate in interpreted['candidates']:
            if candidate['status']!='admitted':continue
            detail={'candidate_id':candidate['candidate_id'],'status':'grounding'};r['candidates'].append(detail)
            at=time.perf_counter()
            try:
                program=SemanticGraphProgram.from_dict(candidate['program'])
                if len(program.operators)>policy.max_operators:raise ValueError('Interpretation exceeds operator bound')
                bound,trace=ground_interpretation(program,candidate['operator_sources'],bundle,request.question,
                    max_holes=policy.max_holes,max_candidates_per_hole=policy.max_candidates_per_hole,use_ontology=policy.use_ontology,
                    ranking_policy=policy.grounding_ranking if information_profile=='nl-conditional-strong-k1-v1' else 'artifact_entry_order_v1')
                quality=candidate['quality_proxy'];proxy=policy.unknown_quality_proxy if quality is None else quality
                detail.update(status='grounded',grounding=trace,bound_program=bound.program.to_dict(),
                    quality_proxy=quality,ranking_quality_proxy=proxy,quality_fallback_used=quality is None)
                choices.append((proxy,candidate['candidate_id'],bound.program))
            except (ValueError,KeyError,TypeError) as error:
                detail.update(status='grounding_failed',error=str(error),grounding=getattr(error,'trace',None))
            finally:r['grounding_ms']+=(time.perf_counter()-at)*1000
        if not choices:
            r.update(status='no_grounded_interpretation',error='No admitted candidate grounded');return finish()
        at=time.perf_counter();quality,identifier,program=min(choices,key=lambda c:(-c[0],c[1]))
        r['selection']={'candidate_id':identifier,'ranking_quality_proxy':quality,'quality_proxy_calibrated':False,
            'algorithm':'highest_grounded_quality_then_candidate_id_v1','estimated_cost_used':False,
            'execution_observations_used':False,'fallback_on_compilation_failure':False}
        r['selected_program']=program.to_dict();r['selection_ms']=(time.perf_counter()-at)*1000
        at=time.perf_counter();r['compilations']=1
        try:r['artifact']=compile_global_program(program,mapping).to_dict()
        except Exception as error:
            r.update(status='global_compilation_failed',error_type=type(error).__name__,error=str(error));return finish()
        finally:r['compilation_ms']=(time.perf_counter()-at)*1000
        r.update(success=True,status='query_prepared')
    except Exception as error:
        r.update(status='frontend_failed',error_type=type(error).__name__,error=str(error))
    return finish()
