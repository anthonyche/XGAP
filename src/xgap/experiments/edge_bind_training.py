"""Four new offline training plans and verified reuse of 28 old observations."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path

from xgap.compilers.rdf_encoding import RdfEdgeEncoding
from xgap.planning.runtime_estimator import FrozenSourceStatistics, SourceStatistics, RuntimeTrainingSample, _hash
from xgap.planning.runtime_work_estimator import extract_work_features, load_frozen_estimator
from xgap.runtime.contracts import FederatedExecutionPlan
from xgap.runtime.physical_strategies import prepare_physical_strategies
from xgap.runtime.semantic_compiler import SemanticBackend
from xgap.semantic.program import SemanticGraphProgram


PROFILE = 'xgap-edge-bind-training-v1'
NAMESPACE = 'https://xgap.test/edge-bind-training-v1/'
PARENT_HASH = '33badbbe8e8ecea1e69c5318902a809219a96d5d4a775e36fd06750070eee177'
PARENT_ROOT = Path('/Users/anthonyche/xgap-data/work-estimator-v2-native-20260912-a2c1908')
ORDER = (('neo4j','source'),('fuseki','target'),('neo4j','target'),('fuseki','source'))
EXCLUDED_IDS = ('B01','B02','B03','B04','B05','WORK-HOLDOUT-01','SPLIT-NL-01',
    'financial-gold-F1','financial-gold-F2','financial-gold-F3','FINANCIAL-NL-01')
NODES = tuple({'id':'eb_'+letter,'bucket':'pair' if letter in 'ab' else 'other'} for letter in 'abcd')
EDGES = tuple({'id':'et_'+str(i),'source':'eb_'+a,'target':'eb_'+b,'weight':w}
    for i,(a,b,w) in enumerate((('a','b',2),('a','b',2),('a','c',5),('b','c',7),('c','d',11),('d','a',13)),1))


def fixture():
    data={'nodes':list(NODES),'edges':list(EDGES)}
    version=_hash(data)
    rows=[*NODES,*EDGES]
    width=sum(len(json.dumps(r,sort_keys=True,separators=(',',':')).encode()) for r in rows)/len(rows)
    stats=FrozenSourceStatistics(PROFILE,version,tuple(SourceStatistics(b,PROFILE,version,len(rows),width,
        'edge-bind-fixture#sha256='+version+';logical-node-and-edge-records') for b in ('fuseki','neo4j')))
    terms={name:{'kind':kind,'representation':NAMESPACE+name} for name,kind in
        (('Vertex','class'),('LINK','relation'),('id','property'),('bucket','property'),('weight','property'))}
    mapping={'mapping_id':PROFILE,'version':'v1','backends':{'fuseki':{'namespace':NAMESPACE}},'term_mappings':{'fuseki':terms}}
    encoding=RdfEdgeEncoding(PROFILE,NAMESPACE+'Edge',NAMESPACE+'source',NAMESPACE+'target',NAMESPACE+'edgeLabel')
    backends={'neo4j':SemanticBackend('neo4j',NAMESPACE),
        'fuseki':SemanticBackend('fuseki',NAMESPACE,backend_mapping=mapping,rdf_edge_encoding=encoding,rdf_node_classes=(NAMESPACE+'Vertex',))}
    ttl=['@prefix eb: <'+NAMESPACE+'> .']
    for n in NODES:
        ttl.append(f'eb:{n["id"]} a eb:Vertex ; eb:id {json.dumps(n["id"])} ; eb:bucket {json.dumps(n["bucket"])} .')
    for e in EDGES:
        ttl.append(f'eb:{e["id"]} a eb:Edge ; eb:id {json.dumps(e["id"])} ; eb:source eb:{e["source"]} ; '
                   f'eb:target eb:{e["target"]} ; eb:edgeLabel eb:LINK ; eb:weight {e["weight"]} .')
    loads=[{'id':'nodes','text':'UNWIND $nodes AS row CREATE (n:Vertex) SET n = row','parameters':{'nodes':list(NODES)}},
        {'id':'edges','text':'UNWIND $edges AS row MATCH (a:Vertex {id:row.source}), (b:Vertex {id:row.target}) '
            'CREATE (a)-[e:LINK]->(b) SET e.id = row.id, e.weight = row.weight','parameters':{'edges':list(EDGES)}}]
    return data,stats,backends,'\n'.join(ttl)+'\n',loads


def prepare_entries():
    _,statistics,backends,_,_=fixture()
    entries=[]
    for backend,endpoint in ORDER:
        query_id='EDGE-BIND-TRAIN-'+backend+'-'+endpoint
        driver='fuseki' if backend=='neo4j' else 'neo4j'
        ops=[{'operator_id':'keys','kind':'match','input_ids':[],'input_kinds':[],'output_kind':'binding_set',
            'parameters':{'node':{'label':'Vertex','properties':{'id':'eb_a'} if endpoint=='source' else {'bucket':'pair'}},
                'entity_field':'key','properties':{}}},
            {'operator_id':'links','kind':'match','input_ids':[],'input_kinds':[],'output_kind':'binding_set',
            'parameters':{'edge':{'label':'LINK'},'entity_field':'edge','source_field':'left','target_field':'right','properties':{'weight':'weight'}}},
            {'operator_id':'join','kind':'join','input_ids':['keys','links'],'input_kinds':['binding_set','binding_set'],'output_kind':'binding_set',
            'parameters':{'left_on':'key','right_on':'left' if endpoint=='source' else 'right'}},
            {'operator_id':'answer','kind':'project','input_ids':['join'],'input_kinds':['binding_set'],'output_kind':'binding_set',
            'parameters':{'projections':{'edge':{'kind':'field','field':'edge'},'weight':{'kind':'field','field':'weight'}}}}]
        program=SemanticGraphProgram.from_dict({'program_id':query_id,'operators':ops,'roots':['answer'],'metadata':{'split_role':'training'}})
        space=prepare_physical_strategies(program,source_bindings={'keys':driver,'links':backend},backends=backends,max_parallelism=1)
        selected=next(c for c in space.candidates if c.strategy_id=='entity_bind/join/left_to_right')
        plan=replace(selected.plan,metadata={**selected.plan.metadata,'query_id':query_id,
            'source_snapshot_versions':{s.backend_id:s.snapshot_version for s in statistics.entries},
            'source_identities':{s.backend_id:{'source_id':s.source_id,'snapshot_version':s.snapshot_version} for s in statistics.entries}})
        if extract_work_features(plan,statistics).unknown_fields:raise ValueError('New training features unavailable')
        entries.append({'query_id':query_id,'endpoint':endpoint,'target_backend':backend,'plan':plan,'program':program.to_dict()})
    return statistics,entries,backends


def expected_rows(endpoint):
    # Independently enumerated edge IDs. Two identical-valued parallel links must
    # survive normalization and binding, including the two-key destination case.
    pairs=(('et_1',2),('et_2',2),('et_3',5)) if endpoint=='source' else (('et_1',2),('et_2',2),('et_6',13))
    return [{'edge':NAMESPACE+edge,'weight':weight} for edge,weight in pairs]


def verified_parent_records(root=PARENT_ROOT, *, expected_parent_hash=PARENT_HASH):
    """Read only sealed training files. No heldout result, cost or answer access."""
    root=Path(root).resolve()
    parent=load_frozen_estimator(root/'frozen_work_estimator.json')
    if parent.model_sha256!=expected_parent_hash:raise ValueError('Frozen parent model hash differs')
    p=json.loads(parent.training_provenance_json)
    collection_name,collection_hash=p['collection_ref'].split('#sha256=')
    pins={}
    def read(name,digest):
        if Path(name).name!=name:raise ValueError('Training records must be local regular files')
        path=root/name
        if path.is_symlink():raise ValueError('Training evidence cannot be a symlink')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Training evidence hash differs: '+name)
        pins[name]=digest
        return json.loads(raw)
    collection=read(collection_name,collection_hash)
    manifest=read(Path(collection['manifest']['path']).name,collection['manifest']['sha256'])
    if FrozenSourceStatistics.from_dict(manifest['statistics'])!=parent.statistics:
        raise ValueError('Parent manifest statistics differ')
    if len(manifest['training'])!=p['sample_count'] or len(collection['training'])!=p['sample_count']:
        raise ValueError('Parent collection sample count differs')
    samples=[];evidence=[]
    for index,(entry,collected) in enumerate(zip(manifest['training'],collection['training'])):
        query_id=entry['query_id'];observation_id=p['training_observation_ids'][index]
        if (entry['split_role']!='training' or collected['query_id']!=query_id or collected['status']!='completed'
                or collected['measurement']['sha256']!=p['measurement_sha256s'][index]):
            raise ValueError('Parent collection training identity differs')
        measured=read(Path(collected['measurement']['path']).name,collected['measurement']['sha256'])
        result=measured['runtime_result']
        if (measured['query_id']!=query_id or measured['split_role']!='training' or not result['success']
                or result['elapsed_ms']!=collected['elapsed_ms']):
            raise ValueError('Parent runtime measurement differs')
        plan=FederatedExecutionPlan.from_dict(entry['plan'])
        sample=RuntimeTrainingSample(observation_id,query_id,plan,result['elapsed_ms'],collected['measurement']['sha256'])
        f=extract_work_features(plan,parent.statistics)
        if f.unknown_fields:raise ValueError('Parent features no longer supported; no automatic migration')
        samples.append(sample)
        evidence.append({'observation_id':sample.observation_id,'query_id':sample.query_id,
            'measurement_sha256':sample.measurement_sha256,'plan_sha256':_hash(plan.to_dict()),'features':f.to_dict(),
            'observed_latency_ms':sample.observed_latency_ms,'split_role':sample.split_role})
    if _hash(evidence)!=p['training_samples_sha256']:
        raise ValueError('Parent training sample hash no longer reconstructs')
    return parent,samples,{'files':pins,'root':str(root),'parent_model_sha256':parent.model_sha256,
        'original_collection_elapsed_ms':collection['collection_elapsed_ms'],
        'original_collection_remote_calls':collection['collection_remote_calls'],'new_collection_calls':0}
