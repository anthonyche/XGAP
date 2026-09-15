"""Frozen strong-mode configuration and ordinary-request assembly; no fitting.

Trusted intake and explicitly caller-pinned request bindings define the admitted
input contract. This does not validate arbitrary NL or promote model proposals.
"""
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import re
import time

from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.practical_execution import FrozenClarificationTool, run_practical_semantic_query
from xgap.agent.practical_planning import BindingAction, BindingEvidence, BindingState, PracticalMode, program_identity
from xgap.agent.practical_question import PracticalQuestionOptions
from xgap.agent.practical_tools import frozen_catalog_acquisition, openai_candidate_acquisition
from xgap.agent.question import run_question
from xgap.agent.strong_planning import ResourceUsage, StrongSearchLimits
from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.compilers.features import default_profile
from xgap.experiments.one_shot_profile import (_fields, _file, _text, _url, _env, _backend,
    _client_spec, native_clients, read_pinned)
from xgap.experiments.schema_source_routing import source_assignments
from xgap.llm.openai_compatible import OpenAICompatibleProviderConfig
from xgap.llm.resolution import M15_RESOLUTION_BASE_SCHEMA, OpenAICompatibleResolutionCandidateProvider
from xgap.planning.equality_key_bounds import FrozenEqualityKeyBounds
from xgap.planning.runtime_work_estimator import frozen_estimator_from_dict
from xgap.runtime.semantic_planning import LogicalSource
from xgap.semantic.intake import DeterministicSemanticIntake
from xgap.semantic.interpretation import InterpretationRequest, TemplateInterpretationProvider
from xgap.semantic.program import SemanticGraphProgram, SemanticHoleKind
from xgap.tools import ToolRegistry


SCHEMA = 'xgap-frozen-practical-profile-v1'
REQUEST_SCHEMA = 'xgap-practical-request-v1'
PHYSICAL_FIELDS = ('max_operators','max_holes','max_local_options','max_physical_candidates',
                   'max_remote_calls','max_parallelism','max_bindings','max_binding_bytes')


def _digest(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):
        raise ValueError('An exact SHA-256 is required')
    return value


def _list(value, maximum, *, empty=False):
    if not isinstance(value,list) or not (0 if empty else 1) <= len(value) <= maximum:
        raise ValueError('Explicit bounded list required')
    if any(not isinstance(v,str) or not v for v in value) or len(set(value)) != len(value):
        raise ValueError('List entries must be distinct nonempty strings')
    return tuple(value)


def _model(root, spec, candidate_count, transport=None):
    _fields(spec, ('provider_id','base_url','model','api_key_env','prompt','temperature','top_p',
        'max_tokens','timeout_seconds','disable_thinking'))
    prompt = _file(root,spec['prompt']).decode('utf-8')
    if (type(spec['disable_thinking']) is not bool or type(spec['timeout_seconds']) not in (int,float)
            or not 0 < spec['timeout_seconds'] <= 120 or type(spec['max_tokens']) is not int
            or not 0 < spec['max_tokens'] <= 4096):
        raise ValueError('Model timeout/output contract invalid')
    config = OpenAICompatibleProviderConfig(provider_id=_text(spec['provider_id']),
        base_url=_url(spec['base_url']), model=_text(spec['model']), api_key_env=_env(spec['api_key_env']),
        temperature=spec['temperature'],top_p=spec['top_p'],max_tokens=spec['max_tokens'],
        candidate_cap=candidate_count,timeout_seconds=spec['timeout_seconds'],
        structured_output_mode='json_schema',structured_schema=M15_RESOLUTION_BASE_SCHEMA,
        prompt_hash=hashlib.sha256(prompt.encode()).hexdigest(),max_repair_calls=0,
        extra_parameters={'chat_template_kwargs':{'enable_thinking':False}} if spec['disable_thinking'] else {})
    return OpenAICompatibleResolutionCandidateProvider(config,prompt,**({} if transport is None else {'transport':transport}))


@dataclass(frozen=True)
class PreparedPracticalRequest:
    request: InterpretationRequest
    provider: TemplateInterpretationProvider
    program: SemanticGraphProgram
    options: PracticalQuestionOptions
    model_providers: dict
    profile_sha256: str
    request_sha256: str
    configuration: tuple
    source_routing: dict | None = None


@dataclass(frozen=True)
class FrozenPracticalProfile:
    root: Path
    sha256: str
    document_json: str

    @classmethod
    def load(cls,path,*,expected_sha256):
        return cls.load_materialized(path,expected_sha256=expected_sha256)[0]

    @classmethod
    def load_materialized(cls,path,*,expected_sha256):
        """Admit once and return the request-local dependency snapshot to its owner."""
        data=read_pinned(path,expected_sha256)
        obj=cls(Path(path).resolve().parent,expected_sha256,data.decode('utf-8'))
        return obj,obj.materialize()  # All modes/dependencies admitted before any call.

    def materialize(self):
        doc=json.loads(self.document_json)
        _fields(doc,('schema_version','profile_id','dataset','intake','operator_sources','catalog',
            'estimator','sources','backends','acquisitions','modes','offline'),('source_schema',))
        if doc['schema_version'] != SCHEMA: raise ValueError('Unsupported practical profile')
        _text(doc['profile_id']);_fields(doc['dataset'],('dataset_id','version'))
        for v in doc['dataset'].values():_text(v)
        if not isinstance(doc['offline'],dict):raise ValueError('Offline provenance must be an object')
        template=json.loads(_file(self.root,doc['intake']))
        intake=DeterministicSemanticIntake(template,artifact_sha256=doc['intake']['sha256'],allow_closed=True)
        _fields(doc['catalog'],('path','bundle_hash'))
        bundle=FrozenResolutionBundle.load(self.root/doc['catalog']['path'],expected_bundle_hash=doc['catalog']['bundle_hash'])
        estimator=None if doc['estimator'] is None else frozen_estimator_from_dict(json.loads(_file(self.root,doc['estimator'])))
        if not isinstance(doc['backends'],dict) or not 1 <= len(doc['backends']) <= 64:
            raise ValueError('Expected 1..64 backends')
        backends,clients={},{}
        for key, spec in doc['backends'].items():
            _text(key);_fields(spec,('semantic','client'))
            backends[key],clients[key]=_backend(spec['semantic'],key),_client_spec(spec['client'])
            p=backends[key].profile or default_profile(key)
            if (p.backend_id!=key or p.engine!=clients[key]['engine'] or
                    p.language.lower()!=('cypher' if clients[key]['engine']=='neo4j' else 'sparql')):
                raise ValueError('Semantic capability and endpoint engine differ')
        if not isinstance(doc['sources'],dict) or not 1 <= len(doc['sources']) <= 64:
            raise ValueError('Expected 1..64 sources')
        sources,identities={},{}
        for key,spec in doc['sources'].items():
            _text(key);_fields(spec,('version','replicas'),('equality_key_bounds',));_text(spec['version'])
            replicas=_list(spec['replicas'],64)
            bounds=None
            if 'equality_key_bounds' in spec:
                pin=spec['equality_key_bounds'];bounds=FrozenEqualityKeyBounds.from_bytes(_file(self.root,pin),
                    expected_sha256=pin['sha256'],source_id=key,snapshot_version=spec['version'])
            for b in replicas:
                if b not in backends or b in identities:raise ValueError('Each backend must identify one logical source')
                identities[b]=(key,spec['version'])
            if len({backends[b].resource_namespace for b in replicas})!=1:
                raise ValueError('Replica namespace mismatch')
            if bounds is not None and any(backends[b].resource_namespace!=bounds.resource_namespace for b in replicas):
                raise ValueError('Equality statistics namespace mismatch')
            sources[key]=LogicalSource(key,spec['version'],replicas,bounds)
        if set(identities)!=set(backends):raise ValueError('Every backend requires a source')
        if estimator is not None:
            if identities!={s.backend_id:(s.source_id,s.snapshot_version) for s in estimator.statistics.entries}:
                raise ValueError('Frozen estimator/source identities mismatch')
            if hasattr(estimator,'reference_backends') and dict(estimator.reference_backends)!={k:v['engine'] for k,v in clients.items()}:
                raise ValueError('Instance estimator reference engines differ')
        holes={h['hole_id']:SemanticHoleKind(h['kind']) for h in template['holes']}
        source_ops={o['operator_id'] for o in template['operators'] if o['kind'] in ('match','traverse')}
        routed='source_schema' in doc
        if routed and (holes or doc['operator_sources']!={} or not isinstance(doc['source_schema'],dict)):
            raise ValueError('Online schema routing requires a closed intake and no supplied source assignments')
        if not isinstance(doc['operator_sources'],dict) or (not routed and set(doc['operator_sources'])!=source_ops):
            raise ValueError('Operator sources must cover every source operator')
        for value in doc['operator_sources'].values():
            if isinstance(value,str) and value in sources:continue
            if isinstance(value,dict) and set(value)=={'$hole'} and holes.get(value['$hole']) is SemanticHoleKind.SOURCE:continue
            raise ValueError('Operator source requires a declared source or source slot')
        acquisitions=doc['acquisitions']
        if not isinstance(acquisitions,dict) or len(acquisitions)>128:raise ValueError('At most128 acquisitions')
        for name,a in acquisitions.items():
            _text(name);_fields(a,('kind','slot','candidate_ids'),('provider','source_id','version','failed_outcomes'))
            kind=a['kind'];slot=a['slot']
            candidates=_list(a['candidate_ids'],8 if kind=='model' else 254)
            if slot not in holes or any(c not in bundle.bindings or bundle.bindings[c].kind!=holes[slot] for c in candidates):
                raise ValueError('Acquisition candidate type/slot mismatch')
            if kind=='model':
                _fields(a,('kind','slot','candidate_ids','provider'))
                if holes[slot] is SemanticHoleKind.ENTITY:raise ValueError('Model cannot resolve entity identity')
                _model(self.root,a['provider'],len(candidates))
            elif kind=='catalog':
                _fields(a,('kind','slot','candidate_ids'))
                if holes[slot] is not SemanticHoleKind.ENTITY:raise ValueError('Catalog schema existence is not intent authority')
            elif kind=='clarification':
                _fields(a,('kind','slot','candidate_ids','source_id','version','failed_outcomes'))
                _text(a['source_id']);_text(a['version'])
                if not set(_list(a['failed_outcomes'],2,empty=True)) <= {'error','unavailable'}:
                    raise ValueError('Unknown clarification failure outcome')
            else:raise ValueError('Unknown acquisition kind')
        _fields(doc['modes'],('exact','performance'))
        modes={}
        for name,raw in doc['modes'].items():
            _fields(raw,('semantic','search','physical','actions'))
            semantic=dict(raw['semantic']);_fields(semantic,('mode','allowed_unvalidated','epsilon','improve_physical'))
            semantic['allowed_unvalidated']=_list(semantic['allowed_unvalidated'],64,empty=True)
            if type(semantic['improve_physical']) is not bool:raise ValueError('improve_physical must be boolean')
            mode=PracticalMode(**semantic)
            if mode.mode!=name or not set(mode.allowed_unvalidated)<=holes.keys():raise ValueError('Mode identity or allowed slot mismatch')
            _fields(raw['physical'],PHYSICAL_FIELDS)
            physical=OneShotPolicy(mode='precision' if name=='exact' else 'performance',**raw['physical'])
            search=dict(raw['search']);_fields(search,('max_depth','max_states','max_actions','max_outcomes',
                'max_terminals_per_state','planning_ms','improvement_actions','resources'))
            _fields(search['resources'],('model_calls','tokens','remote_calls'))
            search['resources']=ResourceUsage(**search['resources']);limits=StrongSearchLimits(**search)
            if len(holes)>physical.max_holes:raise ValueError('Intake hole count exceeds the physical profile')
            if not isinstance(raw['actions'],dict) or not set(raw['actions'])<=acquisitions.keys():
                raise ValueError('Mode references undeclared actions')
            action_ids=[]
            for key,order in raw['actions'].items():
                _fields(order,('search_priority','estimated_ms','token_budget'))
                a=acquisitions[key]; action_id=('llm' if a['kind']=='model' else a['kind'])+':'+a['slot']
                action_ids.append(action_id)
                # Validate even actions not reached for a particular question.
                resource=ResourceUsage(1,order['token_budget'],1) if a['kind']=='model' else ResourceUsage(tokens=order['token_budget'])
                if a['kind']!='model' and order['token_budget']!=0:raise ValueError('Local acquisitions reserve no model tokens')
                BindingAction(action_id,a['slot'],'validate:'+key,(('candidate',a['candidate_ids'][0]),),
                    'profile',self.sha256,estimated_ms=order['estimated_ms'],resources=resource,search_priority=order['search_priority'])
            if len(set(action_ids))!=len(action_ids):raise ValueError('One acquisition per kind/slot in this profile')
            modes[name]=(mode,limits,physical)
        return doc,intake,bundle,estimator,sources,backends,clients,modes

    def prepare(self,raw,*,request_sha256,request_root,mode,materialized=None,model_transports=None,
                acquisition_wrapper=None):
        _digest(request_sha256)
        _fields(raw,('schema_version','question_id','question','trusted_bindings','predictions','clarifications',
            'population','exposure'))
        if raw['schema_version']!=REQUEST_SCHEMA:raise ValueError('Unsupported practical request')
        for k in ('question_id','question','population','exposure'):_text(raw[k])
        cfg=materialized or self.materialize()
        doc,intake,bundle,_,_,_,_,modes=cfg
        if doc!=json.loads(self.document_json):raise ValueError('Prepared configuration differs from this profile')
        if mode not in modes:raise ValueError('Unknown practical mode')
        request=InterpretationRequest(raw['question'],{'query_id':raw['question_id']},intake.required_hard_constraints)
        provider=TemplateInterpretationProvider(intake,doc['operator_sources'])
        program=SemanticGraphProgram.from_dict(provider.interpret(request).payload['program'])
        routing=None
        if 'source_schema' in doc:
            at=time.perf_counter()
            assignments,routing=source_assignments(program,doc['source_schema'],cfg[4])
            routing={**routing,'elapsed_ms':(time.perf_counter()-at)*1000,'scope':'online request preparation; nested in admission'}
            provider=TemplateInterpretationProvider(intake,assignments)
        semantic,limits,physical=modes[mode]
        if len(program.operators)>physical.max_operators:raise ValueError('Intake operator budget exceeded')
        holes={h.hole_id:h.kind for h in program.holes}
        for field in ('trusted_bindings','predictions'):
            values=raw[field]
            if not isinstance(values,dict) or not set(values)<=holes.keys():raise ValueError('Unknown request binding slot')
            if any(c not in bundle.bindings or bundle.bindings[c].kind!=holes[s] for s,c in values.items()):
                raise ValueError('Request binding has wrong type or unknown candidate')
        if set(raw['trusted_bindings']) & set(raw['predictions']):raise ValueError('A prediction cannot override a validated binding')
        # Both modes can receive the same proposal input. EXACT still cannot use
        # it as authority or execute until every required slot is validated.
        if not set(raw['predictions'])<=set(modes['performance'][0].allowed_unvalidated):
            raise ValueError('Unauthorized request prediction')
        evidence=(BindingEvidence('$structure',program_identity(program),'trusted_request','frozen-intake',doc['intake']['sha256']),
            *(BindingEvidence(s,c,'trusted_request','pinned-request',request_sha256) for s,c in raw['trusted_bindings'].items()))
        state=BindingState(tuple(sorted(raw['trusted_bindings'].items())),evidence)
        if not isinstance(raw['clarifications'],dict) or not set(raw['clarifications'])<=doc['acquisitions'].keys():
            raise ValueError('Unknown clarification reference')
        if any(doc['acquisitions'][k]['kind']!='clarification' for k in raw['clarifications']):
            raise ValueError('A clarification response cannot override another provider kind')
        transports=dict(model_transports or {})
        if any(k not in doc['acquisitions'] or doc['acquisitions'][k]['kind']!='model' for k in transports):
            raise ValueError('Transport override must name a configured model action')
        registry=ToolRegistry();actions=[];providers={}
        for key,order in doc['modes'][mode]['actions'].items():
            a=doc['acquisitions'][key];slot=a['slot'];candidates=tuple(a['candidate_ids'])
            common=dict(estimated_ms=order['estimated_ms'],search_priority=order['search_priority'])
            if a['kind']=='catalog':
                action,tool=frozen_catalog_acquisition(program,slot,candidates,bundle.catalog,question=request.question,**common)
            elif a['kind']=='model':
                proposal=_model(self.root,a['provider'],len(candidates),transports.get(key));providers[key]=proposal
                action,tool=openai_candidate_acquisition(program,slot,candidates,proposal,question=request.question,
                    token_budget=order['token_budget'],**common)
            else:
                action=BindingAction('clarification:'+slot,slot,'practical.clarification:'+slot,
                    tuple((f'candidate-{i}',c) for i,c in enumerate(candidates))+tuple((k,None) for k in a['failed_outcomes']),
                    a['source_id'],a['version'],'clarification',**common)
                pin=raw['clarifications'].get(key)
                tool=None
                if pin is not None:
                    _fields(pin,('path','sha256'));_digest(pin['sha256']);_text(pin['path'])
                    tool=FrozenClarificationTool(Path(request_root)/pin['path'],action.tool_name,pin['sha256'])
            actions.append(action)
            if tool is not None:registry.register(acquisition_wrapper(tool) if acquisition_wrapper else tool)
        options=PracticalQuestionOptions(state,semantic,tuple(actions),registry,raw['predictions'],limits,physical,bundle)
        return PreparedPracticalRequest(request,provider,program,options,providers,self.sha256,request_sha256,cfg,routing)

    def run(self,*,request_path,request_sha256,mode,execute=True,backend_clients=None,model_transports=None,
            acquisition_wrapper=None):
        started=time.perf_counter()
        raw=json.loads(read_pinned(request_path,request_sha256))
        cfg=self.materialize()
        q=self.prepare(raw,request_sha256=request_sha256,request_root=Path(request_path).resolve().parent,mode=mode,
            materialized=cfg,model_transports=model_transports,acquisition_wrapper=acquisition_wrapper)
        return self.run_prepared(q,execute=execute,backend_clients=backend_clients,
            preparation_ms=(time.perf_counter()-started)*1000,model_transport_origin='caller_supplied' if model_transports else 'configured')

    def run_prepared(self,q,*,execute=True,backend_clients=None,acquisition_wrapper=None,
                     preparation_ms=0.0,model_transport_origin='configured'):
        """Consume admitted in-memory inputs; late clarification/source captures stay pinned.

        The record runner owns one snapshot per request. No global cache, result
        reuse, or re-reading of profile dependencies after admission is implied.
        """
        started=time.perf_counter()
        if not isinstance(q,PreparedPracticalRequest) or q.profile_sha256!=self.sha256:
            raise ValueError('Prepared request belongs to another profile')
        doc,_,bundle,estimator,sources,backends,client_specs,_=q.configuration
        if doc!=json.loads(self.document_json):raise ValueError('Prepared configuration changed after admission')
        if type(preparation_ms) not in (int,float) or not 0<=preparation_ms<float('inf'):
            raise ValueError('Preparation cost must be finite and nonnegative')
        if acquisition_wrapper:
            registry=ToolRegistry()
            for spec in q.options.resolution_tools.specs():
                registry.register(acquisition_wrapper(q.options.resolution_tools.get(spec.name)))
            q=replace(q,options=replace(q.options,resolution_tools=registry))
        mode=q.options.mode.mode;request_sha256=q.request_sha256
        clients=backend_clients if backend_clients is not None else (native_clients(client_specs) if execute else
            {b:object() for b in client_specs})
        if execute:
            result=run_question(q.request,q.provider,practical_options=q.options,
                catalog_root=self.root/doc['catalog']['path'],catalog_hash=bundle.bundle_hash,
                sources=sources,backends=backends,backend_clients=clients,estimator=estimator)
        else:
            result=run_practical_semantic_query(q.program,initial_state=q.options.initial_state,
                mode=q.options.mode,actions=q.options.actions,resolution_tools=q.options.resolution_tools,
                predictions=q.options.predictions,limits=q.options.limits,physical_profile=q.options.physical_profile,
                operator_sources=q.provider.operator_sources,binding_values=bundle.bindings,sources=sources,
                backends=backends,backend_clients=clients,estimator=estimator,execute=False)
        return {**result,'profile_sha256':self.sha256,'request_sha256':request_sha256,'profile_id':doc['profile_id'],
            'profile_preparation_ms':preparation_ms,'request_total_ms':preparation_ms+(time.perf_counter()-started)*1000,
            'source_routing':q.source_routing,
            'dependency_lifetime':'admitted request snapshot; next request revalidates files',
            'source_statistics_sha256':estimator.statistics.sha256 if estimator else None,
            'estimator_sha256':estimator.model_sha256 if estimator else None,
            'input_scope':'caller-pinned trusted intake and request bindings; not open-domain NL validation',
            'mode_configuration':doc['modes'][mode], 'execution_enabled':execute,
            'client_origin':'caller_supplied' if backend_clients is not None else 'configured' if execute else 'preflight_only',
            'model_transport_origin':model_transport_origin,
            'model_invocations':{k:p.last_invocation.to_dict() for k,p in q.model_providers.items() if p.last_invocation is not None}}
