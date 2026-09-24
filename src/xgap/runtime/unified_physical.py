"""One checked rewrite at a time. No physical-space product or backend effects."""
from collections import Counter
from dataclasses import replace
import json

from xgap.agent.intent_certificate import fingerprint
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.anchor_reduction import depends_on
from xgap.runtime.contracts import RuntimeNode, RuntimeNodeKind as R
from xgap.runtime.physical_strategies import _entity_lineage, _bound_match_artifact
from xgap.runtime.shared_native_reads import _key
from xgap.runtime.source_row_filters import prefilter_source_rows
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.program import SemanticOperatorKind as S
from xgap.runtime.necessary_bind_moves import mandatory_anchor_bind,nested_key_targets


def identity(plan):
    # Ignore construction history; equal executable DAGs deduplicate across paths.
    return fingerprint(dict(nodes=[n.to_dict() for n in plan.nodes], roots=plan.roots,
        max_remote_calls=plan.max_remote_calls, max_parallelism=plan.max_parallelism,
        snapshots=plan.metadata.get('source_identities')))


def finish(plan, nodes, rule, proof, metadata=None):
    result = replace(plan, nodes=tuple(nodes), metadata={**plan.metadata, **(metadata or {}),
        'unified_rewrite': dict(rule=rule, proof=proof, parent=identity(plan), rewrite_count=1)})
    return replace(result, plan_id='unified:'+identity(result)[:24])


class PhysicalMoves:
    def __init__(self, family, schema, backends, policy, sources=None):
        self.programs = {}
        self.native_spj = {}
        self.family, self.schema, self.backends, self.policy = family, schema, backends, policy
        self.sources = sources or {}

    def program(self, index):
        if index not in self.programs:
            self.programs[index] = lower_compact_query(json.loads(self.family.candidates[index].query_json),
                self.schema, version=self.family.language_version, optimize=True)[0]
        return self.programs[index]

    def neighbors(self, index, plan):
        """At most O(nodes^2 + operators^2) distinct proposals, lazily yielded."""
        seen=set()
        for proposal in self._neighbors(index,plan):
            key=identity(proposal)
            if key not in seen:
                seen.add(key);yield proposal

    def _neighbors(self,index,plan):
        if plan.metadata.get('native_spj_pushdown') or plan.metadata.get('native_external_semijoin'):
            return  # Complete source contraction has no coordinator rewrite ports.
        program = self.program(index)
        operators = {o.operator_id:o for o in program.operators}
        consumers = Counter(i for o in program.operators for i in o.input_ids)
        # A single checked source contraction; no trial execution, candidate
        # products, or unchecked intermediate LIMIT. All reads share a backend.
        placement=plan.metadata['source_bindings']
        if len(set(placement.values()))==1:
            from xgap.compilers.native_spj import compile_native_spj
            backend=next(iter(placement.values()))
            key=(index,tuple(sorted(placement.items())))
            try:
                if key not in self.native_spj:
                    self.native_spj[key]=None
                    self.native_spj[key]=compile_native_spj(program,self.backends[backend],self.schema,placement,
                        prefix_topk=True)[0]
                artifact=self.native_spj[key]
                if artifact is None:raise ValueError('Source contraction was not admitted')
                root=plan.roots[0]
                node=RuntimeNode(root,R.REMOTE_QUERY,parameters={'backend_id':backend,'artifact':artifact.to_dict()},
                    semantic_operator_ids=tuple(o.operator_id for o in program.operators))
                proof=artifact.parameters['source_pushdown']
                yield finish(plan,[node],'native_spj_pushdown',proof,dict(native_spj_pushdown=proof,
                    operator_outputs={program.roots[0]:root}))
            except (ValueError,KeyError):
                pass
        elif len(set(placement.values()))==2 and self.policy is not None:
            from xgap.runtime.native_semijoin import semijoin_nodes
            try:
                contraction=semijoin_nodes(program,plan,self.backends,self.schema,self.policy,self.native_spj)
                if contraction:
                    nodes,proof=contraction
                    yield finish(plan,nodes,'native_external_semijoin',proof,
                        dict(native_external_semijoin=proof,operator_outputs={program.roots[0]:plan.roots[0]}))
            except (ValueError,KeyError,StopIteration):pass
        from xgap.runtime.leaf_witness import witness_neighbors
        for nodes,proof in witness_neighbors(json.loads(self.family.candidates[index].query_json),
                program,plan,self.backends,self.policy):
            yield finish(plan,nodes,'leaf_witness',proof)
        # One proved macro transform turns a mandatory scalar anchor into a
        # bounded native key reduction. The old equality/semijoin proof is reused;
        # this does not generate or execute a Cartesian strategy space.
        try:
            anchored=mandatory_anchor_bind(program,plan,self.backends,self.policy)
            if anchored is not None:
                yield finish(plan,anchored.nodes,'entity_bind',dict(kind='mandatory_anchor_fanout',
                    admission=anchored.metadata['anchor_reduction']),anchored.metadata)
        except (ValueError,KeyError,StopIteration):pass
        from xgap.runtime.semantic_compiler import compile_semantic_source
        # Change one logical source placement. Recompile only its unchanged
        # fragment; transformed/shared fragments keep their independently valid seed.
        placement=plan.metadata['source_bindings']
        for op in program.operators:
            if op.operator_id not in placement:continue
            backend=placement[op.operator_id]
            source_identity=plan.metadata['source_identities'][backend]
            source=self.sources.get(source_identity['source_id'])
            if source is None:continue
            original_fragment=compile_semantic_source(op,self.backends[backend])
            old={n.node_id:n for n in original_fragment.nodes}
            actual={n.node_id:n for n in plan.nodes if n.node_id in old}
            if actual!=old:continue
            for alternative in source.replica_backend_ids:
                if alternative==backend or alternative not in self.backends:continue
                try:
                    replacement=compile_semantic_source(op,self.backends[alternative])
                    if replacement.schema!=original_fragment.schema:continue
                    new={n.node_id:n for n in replacement.nodes}
                    if set(new)!=set(old):continue
                    if self.backends[alternative].resource_namespace!=self.backends[backend].resource_namespace:continue
                    metadata={'source_bindings':{**placement,op.operator_id:alternative},
                        'source_identities':{**plan.metadata['source_identities'],alternative:source_identity},
                        'source_snapshot_versions':{**plan.metadata['source_snapshot_versions'],alternative:source.snapshot_version}}
                    yield finish(plan,[new.get(n.node_id,n) for n in plan.nodes],'source_placement',
                        dict(operator=op.operator_id,source=source.source_id,snapshot=source.snapshot_version,
                             before=backend,after=alternative),metadata)
                except ValueError:continue
        from xgap.runtime.shared_match_projections import share_match_projections, PROFILE
        original = {n.node_id:n for n in plan.nodes}
        shared = share_match_projections(replace(plan, metadata={k:v for k,v in plan.metadata.items() if k!=PROFILE}),
                                        program, self.backends, native_key=_key)
        changed = {n.node_id:n for n in shared.nodes}
        for proof in shared.metadata.get(PROFILE,{}).get('proofs',()):
            removed,keep,consumer = (proof[k] for k in ('removed','representative','consumer'))
            representative = replace(original[keep],semantic_operator_ids=tuple(sorted(set(
                original[keep].semantic_operator_ids+original[removed].semantic_operator_ids))))
            nodes = [changed[consumer] if n.node_id==consumer else representative if n.node_id==keep else n
                     for n in plan.nodes if n.node_id!=removed]
            yield finish(plan,nodes,'share_read',proof)
        # One identical-read contraction, keeping separate consumer input ports.
        readers = [n for n in plan.nodes if _key(n, plan) is not None]
        uses = {n.node_id:{m.node_id for m in plan.nodes if n.node_id in m.inputs} for n in readers}
        for pos, first in enumerate(readers):
            for second in readers[pos+1:]:
                if _key(first, plan) != _key(second, plan) or uses[first.node_id] & uses[second.node_id]:
                    continue
                nodes = [replace(n, inputs=tuple(first.node_id if p==second.node_id else p for p in n.inputs),
                    semantic_operator_ids=tuple(sorted(set(first.semantic_operator_ids+second.semantic_operator_ids)))
                        if n.node_id==first.node_id else n.semantic_operator_ids)
                    for n in plan.nodes if n.node_id!=second.node_id]
                outputs = {k:first.node_id if v==second.node_id else v for k,v in plan.metadata['operator_outputs'].items()}
                yield finish(plan,nodes,'share_read',dict(keep=first.node_id,remove=second.node_id),{'operator_outputs':outputs})
        # Reuse the existing equality proof, but apply only one native-node change.
        bare = replace(plan, metadata={k:v for k,v in plan.metadata.items() if k!='source_row_prefilters'})
        screened = prefilter_source_rows(program, bare)
        for old,new in zip(plan.nodes,screened.nodes):
            if old==new:continue
            # Never wrap an already screened native query again.
            if 'necessary_row_filters' in old.parameters.get('artifact',{}).get('parameters',{}):continue
            yield finish(plan,[new if n.node_id==old.node_id else n for n in plan.nodes],
                'prefilter',dict(node=old.node_id,admission=screened.metadata.get('source_row_prefilters')))
        # One exclusive inner-join entity bind. The original join stays in place.
        lineage = _entity_lineage(operators,plan.metadata['schemas'])
        for join in program.operators:
            if join.kind is not S.JOIN:continue
            for side in (0,1):
                driver,target = join.input_ids[side],join.input_ids[1-side]
                field = join.parameters['left_on' if side==0 else 'right_on']
                other = join.parameters['right_on' if side==0 else 'left_on']
                try:
                    if not lineage(driver,field):continue
                    for match,chain,column in nested_key_targets(target,other,operators,plan.metadata['schemas'],consumers,set(program.roots)):
                        remote = next(n for n in plan.nodes if n.node_id==match.operator_id+'/native')
                        # Shared reads require a separate all-consumer proof and are not rebound.
                        if remote.kind is not R.REMOTE_QUERY or len(remote.semantic_operator_ids)!=1:continue
                        output = plan.metadata['operator_outputs'][driver]
                        if depends_on(plan,output,remote.node_id):continue
                        artifact,parameter = _bound_match_artifact(QueryArtifact.from_dict(remote.parameters['artifact']),
                            self.backends[remote.parameters['backend_id']],max_bindings=self.policy.max_bindings,
                            max_binding_bytes=self.policy.max_binding_bytes,identity_column=column,capped_key_work=True)
                        bound = replace(remote,kind=R.REMOTE_BIND_QUERY,inputs=(output,),parameters={**remote.parameters,
                            'artifact':artifact.to_dict(),'bind_field':field,'parameter':parameter,'max_bindings':self.policy.max_bindings})
                        yield finish(plan,[bound if n.node_id==remote.node_id else n for n in plan.nodes],'entity_bind',
                            dict(join=join.operator_id,driver=driver,target=match.operator_id,chain=chain))
                        bound_plan=replace(plan,nodes=tuple(bound if n.node_id==remote.node_id else n for n in plan.nodes))
                        for nodes,proof in witness_neighbors(json.loads(self.family.candidates[index].query_json),
                                program,bound_plan,self.backends,self.policy):
                            yield finish(plan,nodes,'leaf_witness',dict(**proof,bind_driver=driver))
                except (ValueError,KeyError,StopIteration):
                    continue
