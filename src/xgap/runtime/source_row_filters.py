"""Prove mandatory row equalities before adding conservative native screening."""
from collections import defaultdict
from dataclasses import replace
from functools import lru_cache
import hashlib
import json

from xgap.compilers.necessary_row_filters import add_necessary_row_filters
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNodeKind as R
from xgap.semantic.program import SemanticGraphProgram, SemanticOperatorKind as S


PROFILE='mandatory-source-row-prefilter-v1'


def _equalities(condition):
    if condition.get('op')=='and':
        for c in condition['args']:yield from _equalities(c)
    elif (set(condition)=={'op','field','value'} and condition['op']=='eq' and
            type(condition['value']) in (str,bool)):
        yield condition


def prefilter_source_rows(program: SemanticGraphProgram,plan: FederatedExecutionPlan) -> FederatedExecutionPlan:
    if 'source_row_prefilters' in plan.metadata:return plan
    operators={o.operator_id:o for o in program.operators};schemas=plan.metadata.get('schemas',{})
    if set(schemas)!=set(operators):return plan
    consumers=defaultdict(set);roots=set(program.roots)
    for o in program.operators:
        for child in o.input_ids:consumers[child].add(o.operator_id)

    @lru_cache(None)
    def preserved(identifier,field,stop):
        if identifier==stop:return True
        if identifier in roots or not consumers[identifier]:return False
        for parent_id in consumers[identifier]:
            parent=operators[parent_id]
            if field not in schemas[parent_id]['fields']:return False
            if parent.kind is S.PROJECT:
                if parent.parameters['projections'].get(field)!={'kind':'field','field':field}:return False
            elif parent.kind is S.JOIN:
                left,right=parent.input_ids
                if (right==identifier and field in schemas[left]['fields'] and
                        not parent.parameters['left_on']==parent.parameters['right_on']==field):return False
            elif parent.kind not in (S.FILTER,S.UNION):return False
            if not preserved(parent_id,field,stop):return False
        return True

    matches=[o for o in program.operators if o.kind is S.MATCH]
    selected=defaultdict(list);proof=[];count=0
    for enforcing in program.operators:
        if enforcing.kind is not S.FILTER:continue
        for condition in _equalities(enforcing.parameters.get('condition',{})):
            field=condition['field']
            for source in matches:
                if count>=64:break
                # Only scalar projections retain their native column name;
                # entity normalization, paths, renamed fields and lineage guesses
                # cannot be used to manufacture an early native condition.
                if (field not in source.parameters.get('properties',{}) or
                        not preserved(source.operator_id,field,enforcing.operator_id)):continue
                if condition in selected[source.operator_id]:continue
                selected[source.operator_id].append(dict(condition));count+=1
                proof.append({'source_operator':source.operator_id,'enforcing_filter':enforcing.operator_id,'condition':dict(condition)})
    if not selected:return plan
    nodes=[];applied=[];declined=[]
    for n in plan.nodes:
        candidates=[s for s in n.semantic_operator_ids if s in selected and n.node_id==s+'/native']
        if n.kind not in (R.REMOTE_QUERY,R.REMOTE_BIND_QUERY) or len(candidates)!=1:
            nodes.append(n);continue
        source=candidates[0]
        try:
            artifact=add_necessary_row_filters(QueryArtifact.from_dict(n.parameters['artifact']),selected[source])
            nodes.append(replace(n,parameters={**n.parameters,'artifact':artifact.to_dict()}));applied.append(source)
        except (ValueError,KeyError,TypeError) as error:
            nodes.append(n);declined.append({'source_operator':source,'reason':str(error)})
    if not applied:return plan
    result=replace(plan,nodes=tuple(nodes),metadata={**plan.metadata,'source_row_prefilters':{
        'profile':PROFILE,'applications':[p for p in proof if p['source_operator'] in applied],
        'native_nodes':applied,'declined':declined,'original_filters_retained':True,
        'selection':'first64 proved string/boolean equality source applications in semantic input order',
        'semantic_claim':'necessary screening only; final typed predicates decide answers',
        'remote_calls_added':0,'selectivity_estimate':None}})
    raw=json.dumps(result.to_dict(),sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return replace(result,plan_id='prefilter:'+hashlib.sha256(raw).hexdigest()[:20])
