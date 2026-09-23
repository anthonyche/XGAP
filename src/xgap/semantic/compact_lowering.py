"""Ptime graph intent -> existing semantic operators, without executing a query."""

from collections import defaultdict
from copy import deepcopy

from xgap.semantic.compact_query import LOWERING, LOWERING_V2, validate_query
from xgap.semantic.parameter_contract import validate_program_parameters
from xgap.semantic.program import SemanticGraphProgram


class _Builder:
    def __init__(self):
        self.ops,self.sources,self.fields,self.kinds=[],{},{},{}

    def add(self,kind,inputs=(),*,fields=(),logical_source=None,**parameters):
        if len(self.ops)>=64: raise ValueError('Lowered compact program exceeds64 operators')
        identifier='cq'+str(len(self.ops))
        output='grouped_bindings' if kind=='aggregate' else self.kinds[inputs[0]] if kind in ('filter','order_limit','union') else 'binding_set'
        self.ops.append({'operator_id':identifier,'kind':kind,'input_ids':list(inputs),
            'input_kinds':[self.kinds[i] for i in inputs],'output_kind':output,
            'parameters':parameters,'constraints':[],'required_capabilities':[]})
        self.fields[identifier]=set(fields);self.kinds[identifier]=output
        if logical_source is not None:self.sources[identifier]=logical_source
        return identifier

    def project(self,item,projections):
        return self.add('project',(item,),fields=projections,projections=projections)

    def retain(self,item,fields):
        return self.project(item,{f:{'kind':'field','field':f} for f in sorted(fields)})

    def filter(self,item,conditions):
        if not conditions:return item
        return self.add('filter',(item,),fields=self.fields[item],condition=conditions[0] if len(conditions)==1 else {'op':'and','args':conditions})

    def union(self,items):
        if not items:raise ValueError('No source declares coverage for a required read')
        result=items[0]
        for other in items[1:]:
            if self.fields[result]!=self.fields[other]:raise ValueError('Internal union schema mismatch')
            result=self.add('union',(result,other),fields=self.fields[result])
        return result

    def join(self,left,right,identities):
        common=self.fields[left]&self.fields[right]
        keys=common&identities
        if not keys:raise ValueError('Compact patterns must be connected by a shared node/edge variable')
        key=sorted(keys)[0]; prefix='j'+str(len(self.ops))+'_'
        renamed={f:prefix+f if f in common and f!=key else f for f in self.fields[right]}
        fields=self.fields[left]|set(renamed.values())
        result=self.add('join',(left,right),fields=fields,left_on=key,right_on=key,right_prefix=prefix)
        # Every repeated variable is an equality, not merely the first join key.
        extra=common-{key}
        if extra:
            result=self.filter(result,[{'op':'eq','field':f,'right_field':renamed[f]} for f in sorted(extra)])
            result=self.retain(result,self.fields[left]|self.fields[right])
        return result


class _Lowerer:
    def __init__(self,query,schema,version='v1',optimize=False):
        self.version=version
        self.optimize=optimize
        self.q=validate_query(deepcopy(query),version=version);self.b=_Builder()
        if not isinstance(schema,dict):raise ValueError('Frozen source schema is required')
        self.views={k:v for k,v in schema.items() if isinstance(v,dict) and 'nodes' in v and 'edges' in v}
        if not 1<=len(self.views)<=64:raise ValueError('Compact profile needs1..64 declared source views')
        for view in self.views.values():
            if not isinstance(view['nodes'],dict) or not isinstance(view['edges'],list):raise ValueError('Invalid frozen source coverage')
        self.identity=schema.get('identity_property')
        if not isinstance(self.identity,str) or not self.identity:raise ValueError('Frozen identity property is missing')
        self.nodes={n['var']:n for n in self.q['nodes']};self.edges={e['var']:e for e in self.q['edges']}
        self.path=self.q['path'];self.variables={**self.nodes,**self.edges}
        self.ids={v:'v'+str(i) for i,v in enumerate(self.variables)}
        self.refcols={};self.holes=[];self.entity_refs={}
        for i,node in enumerate(self.q['nodes']):
            if not any(node['type'] in v['nodes'] for v in self.views.values()):raise ValueError('Unknown node type: '+node['type'])
            if node['entity'] is not None:
                hole='ce'+str(i);self.entity_refs[node['var']]={'$hole':hole}
                self.holes.append({'hole_id':hole,'kind':'entity','mention':node['entity'],'required':True,'candidates':[],'is_resolved':False})
        self.units=[];self.covered=set();self.decisions=[]

    def column(self,ref):
        var,prop=ref['var'],ref['property']
        if self.path and var==self.path['var']:
            if prop!='length':raise ValueError('A bounded path exposes only its length and declared endpoint variables')
            return 'path_length'
        if var not in self.variables:raise ValueError('Unknown graph variable: '+var)
        if prop is None:return self.ids[var]
        if prop==self.identity:raise ValueError('Use variable identity, not a raw technical identity property')
        key=(var,prop)
        if key not in self.refcols:self.refcols[key]='f'+str(len(self.refcols))
        return self.refcols[key]

    def descriptor(self,var):
        node=self.nodes[var]
        return {'label':node['type'],'properties':{self.identity:self.entity_refs[var]} if var in self.entity_refs else {}}

    def edge_read(self,label,left,right,left_col,right_col,edge_col,properties):
        views=[]
        for name,view in sorted(self.views.items()):
            matches=[e for e in view['edges'] if e['label']==label and e['source']==left['label'] and e['target']==right['label']]
            if not matches:continue
            if any(not set(properties.values())<=set(e['properties']) for e in matches):
                raise ValueError('Partial edge-attribute coverage is unsupported; cannot omit a source')
            views.append(name)
        parts=[]
        # A reused endpoint variable can express a self-loop without output alias collision.
        original_right=right_col
        if left_col==right_col:right_col='self_'+str(len(self.b.ops))
        fields={left_col,right_col,edge_col,*properties}
        for name in views:
            parts.append(self.b.add('match',fields=fields,logical_source=name,edge={'label':label},source_field=left_col,
                target_field=right_col,entity_field=edge_col,properties=properties,**{'source':left,'target':right}))
        result=self.b.union(parts)
        if original_right!=right_col:
            result=self.b.filter(result,[{'op':'eq','field':left_col,'right_field':right_col}])
            result=self.b.retain(result,fields-{right_col})
        self.decisions.append({'kind':'edge','label':label,'sources':views,'coverage':'union of all declared matching views'})
        return result

    def local_conditions(self, item):
        """Only conjuncts whose operands are available on this relation."""
        return [c for c in self.conditions if {c['field']} | (
            {c['right_field']} if 'right_field' in c else set()) <= self.b.fields[item]]

    def path_read(self, anchors=()):
        p=self.path;branches=[];b=self.b
        for hops in range(p['min_hops'],p['max_hops']+1):
            nodes=[self.ids[p['source']]]+['pi'+str(hops)+'_'+str(i) for i in range(1,hops)]+[self.ids[p['target']]]
            edgecols=['pe'+str(hops)+'_'+str(i) for i in range(hops)]
            times=['pt'+str(hops)+'_'+str(i) for i in range(hops)]
            result=None;conditions=[]
            for i in range(hops):
                left=self.descriptor(p['source']) if i==0 else {'label':self.nodes[p['source']]['type']}
                right=self.descriptor(p['target']) if i==hops-1 else {'label':self.nodes[p['target']]['type']}
                props={times[i]:p['time']['property']} if p['time'] else {}
                part=self.edge_read(p['type'],left,right,nodes[i],nodes[i+1],edgecols[i],props)
                local=[];incremental=[]
                if p['time']:
                    t=p['time']
                    for bound,op in [('lower','ge' if t['lower_inclusive'] else 'gt'),('upper','le' if t['upper_inclusive'] else 'lt')]:
                        if t[bound] is not None:local.append({'op':op,'field':times[i],'value':t[bound],'value_type':'timestamp_ms'})
                    if i and t['increasing']:incremental.append({'op':'lt','field':times[i-1],'right_field':times[i],'value_type':'timestamp_ms'})
                if self.optimize:
                    part=b.filter(part,local)
                result=part if result is None else b.join(result,part,set(nodes)|set(edgecols))
                if self.optimize:
                    if i==0:
                        for anchor in anchors:
                            result=b.join(result,anchor,set(nodes)|set(edgecols))
                    if p['mode']=='ACYCLIC':
                        incremental.extend({'op':'ne','field':nodes[j],'right_field':nodes[i+1]} for j in range(i+1))
                    result=b.filter(result,incremental)
                else:
                    conditions.extend(local+incremental)
            if p['mode']=='ACYCLIC' and not self.optimize:
                conditions.extend({'op':'ne','field':nodes[i],'right_field':nodes[j]} for i in range(hops+1) for j in range(i+1,hops+1))
            result=b.filter(result,conditions)
            projections={self.ids[v]:{'kind':'field','field':self.ids[v]} for v in (p['source'],p['target'])}
            projections['path_length']={'kind':'literal','value':hops}
            branches.append(b.project(result,projections))
        self.covered.update((p['source'],p['target']))
        return b.union(branches)

    def node_reads(self):
        for var,node in self.nodes.items():
            required={prop:col for (v,prop),col in self.refcols.items() if v==var}
            groups=defaultdict(dict)
            for prop,col in required.items():
                providers=tuple(name for name,view in sorted(self.views.items()) if
                    prop in view['nodes'].get(node['type'],{}).get('properties',[]))
                if not providers:raise ValueError('No declared source for node property '+prop)
                groups[providers][col]=prop
            if not required and var not in self.covered:
                groups[tuple(name for name,view in sorted(self.views.items()) if node['type'] in view['nodes'])]={}
            for providers,properties in groups.items():
                parts=[self.b.add('match',fields={self.ids[var],*properties},logical_source=name,node=self.descriptor(var),
                    entity_field=self.ids[var],properties=properties) for name in providers]
                self.units.append(self.b.union(parts));self.covered.add(var)
                self.decisions.append({'kind':'node_properties','var':var,'properties':list(properties.values()),
                    'sources':list(providers),'coverage':'union of all providers; groups partition requested properties'})

    def lower(self,program_id):
        b=self.b;output_refs=[]
        for pred in self.q['where']:
            self.column(pred['left'])
            if 'var' in pred['right']:self.column(pred['right'])
            elif pred['left']['property'] is None:
                raise ValueError('Literal canonical identity predicates require a named entity binding')
        for expr in self.q['select'].values():
            ref=expr if 'var' in expr else expr['field']
            if ref is not None:self.column(ref);output_refs.append(ref)
            if 'aggregate' in expr and expr['aggregate']!='count' and ref is None:raise ValueError('Numeric aggregate needs a field')
        self.conditions=[]
        for pred in self.q['where']:
            right=pred['right'];condition={'op':pred['op'],'field':self.column(pred['left'])}
            condition.update({'right_field':self.column(right)} if 'var' in right else {'value':right['value']})
            if pred['value_type']!='scalar':condition['value_type']=pred['value_type']
            self.conditions.append(condition)
        anchors=[]
        if self.optimize:
            # Create property relations early so a selective start property can
            # constrain EACH path prefix, including model-generated business IDs.
            for edge in self.q['edges']+([self.path] if self.path else []):
                self.covered.update((edge['source'],edge['target']))
            self.node_reads()
            self.units=[b.filter(u,self.local_conditions(u)) for u in self.units]
            if self.path:
                start=self.ids[self.path['source']]
                anchors=[u for u in self.units if start in b.fields[u] and self.local_conditions(u)]
        for edge in self.q['edges']:
            properties={col:prop for (v,prop),col in self.refcols.items() if v==edge['var']}
            unit=self.edge_read(edge['type'],self.descriptor(edge['source']),self.descriptor(edge['target']),
                self.ids[edge['source']],self.ids[edge['target']],self.ids[edge['var']],properties)
            self.units.append(b.filter(unit,self.local_conditions(unit)) if self.optimize else unit)
            self.covered.update((edge['source'],edge['target']))
        if self.path:self.units.append(self.path_read(anchors))
        if not self.optimize:self.node_reads()
        pending=list(self.units);result=pending.pop(0)
        identities=set(self.ids.values())
        while pending:
            match=next((i for i,p in enumerate(pending) if b.fields[p]&b.fields[result]&identities),None)
            if match is None:raise ValueError('Disconnected compact query is outside the admitted profile')
            result=b.join(result,pending.pop(match),identities)
        result=b.filter(result,self.conditions)
        keys=self.q['deduplicate_by' if self.version == 'v1' else 'contribution_by']
        contribution=None
        if keys is not None:
            if self.version == 'v1' and any(ref['var'] not in keys for ref in output_refs):
                raise ValueError('Post-distinct output values must belong to the retained node/edge variables')
            retained=set(keys)
            if self.version == 'v2':
                for ref in output_refs:
                    if self.path and ref['var']==self.path['var']:
                        retained.update((self.path['source'],self.path['target']))
                    else:retained.add(ref['var'])
            fields={self.ids[v] for v in retained}|{self.column(r) for r in output_refs}
            result=b.retain(result,fields)
            if self.version == 'v2':
                contribution={'declared_anchors':list(keys),'retained_identity_variables':sorted(retained),
                    'retained_columns':sorted(fields),'operator_id':result,
                    'meaning':'distinct joint contribution tuples; witnesses not in this tuple are existential'}
        groups=[];aggregations={};projections={}
        for alias,expr in self.q['select'].items():
            if 'var' in expr:
                col=self.column(expr);groups.append(col)
            else:
                col='agg'+str(len(aggregations))
                aggregations[col]={'op':expr['aggregate'],'field':self.column(expr['field']) if expr['field'] else None,'distinct':expr['distinct']}
            projections[alias]={'kind':'field','field':col}
        if aggregations:
            groups=list(dict.fromkeys(groups))
            result=b.add('aggregate',(result,),fields=set(groups)|set(aggregations),group_by=groups,aggregations=aggregations)
        result=b.project(result,projections)
        if self.q['order_by']:
            result=b.add('order_limit',(result,),fields=b.fields[result],order_by=self.q['order_by'],limit=self.q['limit'])
        raw={'program_id':program_id,'operators':b.ops,'roots':[result],'holes':self.holes,
            'metadata':{'compact_lowering':{'profile':LOWERING if self.version == 'v1' else LOWERING_V2,'source_coverage':self.decisions,
                'columns':[{ 'var':v,'property':p,'column':col} for (v,p),col in self.refcols.items()],
                'path_result_semantics':'distinct (source,target,length) reachability; no path identity output',
                'deduplication_semantics':'distinct retained identities and selected scalar values',
                'backend_calls':0,'fit_calls':0,'response_repair':False}}}
        if self.version == 'v2':raw['metadata']['compact_lowering']['contribution_projection']=contribution
        if self.optimize:raw['metadata']['compact_lowering']['execution_rewrite']='early-path-constraints-v1'
        validate_program_parameters(raw)
        return SemanticGraphProgram.from_dict(raw),dict(b.sources)


def lower_compact_query(query,source_schema,*,program_id='compact-query',version='v1',optimize=False):
    if type(optimize) is not bool:raise ValueError('Compact optimization must be an explicit boolean')
    try:
        return _Lowerer(query,source_schema,version,optimize).lower(program_id)
    except ValueError as error:
        if not optimize or str(error) != 'Lowered compact program exceeds64 operators':
            raise
        # An optional rewrite must not remove an already admitted feasible seed.
        program,sources=_Lowerer(query,source_schema,version,False).lower(program_id)
        program.metadata['compact_lowering']['execution_rewrite']='legacy-budget-fallback'
        program.metadata['compact_lowering']['rewrite_stop_reason']='64_operator_limit'
        return program,sources
