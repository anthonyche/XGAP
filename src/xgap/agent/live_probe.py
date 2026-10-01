"""Bind an explicitly declared statistics policy to the actual public NL family.

No private user/reference input enters this module. Preparing targets performs no
source query. A capped count is a cardinality category, not a scan-work bound.
The declared prior is an assumption recorded with every request, never calibrated
from this request's gold answer, observed category or winning execution plan.
"""
from dataclasses import asdict, dataclass, replace
import math

from xgap.agent.intent_certificate import canonical, fingerprint
from xgap.agent.unified_information import InformationTarget
from xgap.agent.unified_lookahead import cost
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.contracts import RuntimeNodeKind as R


@dataclass(frozen=True)
class LiveProbePolicy:
    policy_id: str
    basis: str
    candidate_prior: str = 'uniform_over_actual_public_family'
    max_targets: int = 4
    threshold: int = 100
    sparse_rows: float = 50.0
    dense_rows: float = 10000.0
    probabilities: tuple[float, ...] = (.6,.3,.1)
    action_cost: float = .1
    row_cost: float = .001
    bind_fraction: float = .1
    bind_startup: float = .25

    def __post_init__(self):
        if (not isinstance(self.policy_id,str) or not self.policy_id or not isinstance(self.basis,str)
                or not self.basis.strip() or self.candidate_prior!='uniform_over_actual_public_family'
                or type(self.max_targets) is not int or not 1<=self.max_targets<=16
                or type(self.threshold) is not int or not 1<=self.threshold<=100000):
            raise ValueError('Explicit bounded live-probe policy required')
        for value in (self.sparse_rows,self.dense_rows,self.action_cost,self.row_cost,
                      self.bind_fraction,self.bind_startup):cost(value)
        if (self.sparse_rows>self.threshold or self.dense_rows<=self.threshold or self.bind_fraction>1
                or not isinstance(self.probabilities,tuple) or len(self.probabilities)!=3):
            raise ValueError('Invalid cardinality categories or probability model')
        for value in self.probabilities:cost(value)
        if not math.isclose(sum(self.probabilities),1,rel_tol=0,abs_tol=1e-12) or sum(self.probabilities[:2])<=0:
            raise ValueError('Complete probabilities need positive informative mass')


def policy_from_dict(raw):
    if raw is None:return None
    raw=dict(raw);raw['probabilities']=tuple(raw['probabilities'])
    return LiveProbePolicy(**raw)


def capped_count(artifact,cap):
    """Wrap only host-compiled inline native read fragments; parameters survive."""
    if artifact.source_path is not None or artifact.kind!='compiled':
        raise ValueError('Only compiled inline native read fragments can be probed')
    text=artifact.text.strip().rstrip(';')
    if artifact.language=='sparql' and text.upper().startswith('SELECT '):
        query='SELECT (COUNT(*) AS ?value) WHERE { { SELECT * WHERE { {\n'+text+'\n} } LIMIT '+str(cap)+' } }'
    elif (artifact.language=='cypher' and text.upper().startswith(('MATCH ','OPTIONAL MATCH ','CALL {'))
            and artifact.parameters.get('compiler') in ('semantic_node_match_v1','semantic_edge_match_v1')):
        query='CALL {\n'+text+'\n}\nWITH * LIMIT '+str(cap)+'\nRETURN count(*) AS value'
    else:raise ValueError('Information probe requires a supported compiled SELECT/MATCH read')
    parameters={k:v for k,v in artifact.parameters.items() if k not in (
        'rdf_result_encoding','expected_result_columns','output_columns','rdf_binding_checkpoint')}
    parameters.update(expected_result_columns=['value'],output_columns=['value'])
    return QueryArtifact('probe:'+fingerprint(artifact.to_dict())[:24],artifact.language,query,
        parameters=parameters)


def bind_live_probes(settings,family,seeds,sources):
    """Build a deterministic bounded registry after proposal, before online search.

    Identical compiler fragments share one probe across candidate/operator pairs.
    Broad Traverse fragments and multi-operator contractions are not admitted.
    None of the arguments exposes private intent, answers or backend clients.
    """
    policy=settings.live_probe_policy
    if not isinstance(policy,LiveProbePolicy) or settings.limits.aggregation!='expectation':
        raise ValueError('Live binding must explicitly request expectation and a public prior policy')
    if settings.information_targets or settings.candidate_weights is not None:
        raise ValueError('Live binding cannot silently replace a frozen family registry/prior')
    registry={};skipped=0
    for index,(plan,_,_) in sorted(seeds.items()):
        candidate=family.candidates[index]
        for node in plan.nodes:
            if node.kind is not R.REMOTE_QUERY or len(node.semantic_operator_ids)!=1:continue
            artifact=QueryArtifact.from_dict(node.parameters['artifact'])
            # Match identity projections are host compiled. Traverse requires a
            # different cardinality model and is deliberately outside this v1.
            if (not node.node_id.endswith('/native') or artifact.parameters.get('compiler')
                    not in ('semantic_node_match_v1','semantic_edge_match_v1')):
                skipped+=1;continue
            backend=node.parameters['backend_id']
            identity=plan.metadata['source_identities'][backend]
            source=sources.get(identity['source_id'])
            if source is None or backend not in source.replica_backend_ids:
                raise ValueError('Live target source does not match its admitted seed')
            if identity.get('snapshot_version',source.snapshot_version)!=source.snapshot_version:
                raise ValueError('Live target snapshot changed')
            try:probe=capped_count(artifact,policy.threshold+1)
            except ValueError:
                skipped+=1;continue
            key=fingerprint([backend,source.source_id,source.snapshot_version,artifact.language,
                             artifact.text,artifact.parameters])
            item=registry.setdefault(key,dict(probe=probe,backend=backend,source=source,bindings=set()))
            item['bindings'].add((candidate.candidate_id,node.semantic_operator_ids[0]))
    # E[posterior rows] equals the prior, including unknown's unchanged state.
    # A probe cannot earn a score improvement merely by revealing cheap rows
    # when there is no contingent physical plan choice.
    psmall,pbig,punknown=policy.probabilities
    prior=(psmall*policy.sparse_rows+pbig*policy.dense_rows)/(psmall+pbig)
    targets=[];oversized=0
    for key,item in sorted(registry.items())[:policy.max_targets]:
        source=item['source']
        artifact_json=canonical(item['probe'].to_dict())
        if len(artifact_json.encode())>65536 or len(item['bindings'])>4096:
            oversized+=1;continue
        targets.append(InformationTarget(name='fragment-count:'+key,backend=item['backend'],
            source_id=source.source_id,version=source.snapshot_version,kind='probe',
            artifact_json=artifact_json,thresholds=(policy.threshold,),
            labels=('small','large','unknown'),row_estimates=(policy.sparse_rows,policy.dense_rows,prior),
            probabilities=policy.probabilities,action_cost=policy.action_cost,row_cost=policy.row_cost,
            bind_fraction=policy.bind_fraction,bind_startup=policy.bind_startup,
            bindings=tuple(sorted(item['bindings'])),prior_rows=prior))
    bound=replace(settings,live_probe_policy=None,candidate_weights=(1.0,)*len(family.candidates),
                  information_targets=tuple(targets))
    receipt=dict(schema_version='xgap-live-probe-binding-v1',policy=asdict(policy),
        public_family_sha256=family.identity,candidate_ids=[c.candidate_id for c in family.candidates],
        candidate_prior=policy.candidate_prior,candidate_weights=list(bound.candidate_weights),
        registered_targets=[asdict(t) for t in targets],available_fragments=len(registry),
        omitted_by_capacity=max(0,len(registry)-policy.max_targets),oversized_targets=oversized,
        unsupported_fragments=skipped,
        backend_calls=0,private_inputs_read=0,
        scope='Capped compiled Match result categories; not a scan bound or calibrated cardinality estimator')
    return bound,receipt
