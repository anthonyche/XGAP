"""Portable RDFLib adapter for development checks, never a real Fuseki score."""
from dataclasses import replace
import hashlib
import json
from urllib.parse import quote
from rdflib import Graph,Literal,Namespace,URIRef,RDF
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.backends.fuseki_client import FusekiClient
from xgap.compilers.features import default_profile
from xgap.compilers.rdf_encoding import RdfEdgeEncoding
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime.semantic_compiler import SemanticBackend
from xgap.runtime.semantic_planning import LogicalSource
from xgap.experiments.ch6_workload import public_schema


def local_runtime(facts):
    ns=Namespace('https://xgap.dev/ch6/schema/');resource='https://xgap.dev/ch6/resource/'
    def uri(kind,value):return URIRef(resource+kind+hashlib.sha256(value.encode()).hexdigest())
    graphs={n:Graph() for n in ('graph','control')};calls=[]
    for node in facts['nodes']:
        for name,g in graphs.items():
            u=uri('n',node['id']);g.add((u,RDF.type,ns[node['type']]))
            for prop,value in node.items():
                if prop in ('type','identity'):continue
                if prop==facts['control_property'] and name!='control':continue
                if name=='control' and prop not in ('id',facts['control_property']):continue
                g.add((u,ns[prop],Literal(value)))
    for label,edges in facts['relations'].items():
        for e in edges:
            # Scope views are separate typed memberships of one original edge;
            # separate resources preserve a functional edgeLabel per view.
            u=uri('e',label+':'+e['id']);g=graphs['graph']
            g.add((u,RDF.type,ns.Edge));g.add((u,ns.source,uri('n',e['from'])));g.add((u,ns.target,uri('n',e['to'])))
            g.add((u,ns.edgeLabel,ns[label]))
            for prop,value in e.items():
                if prop not in ('from','to'):g.add((u,ns[prop],Literal(value)))
    kinds={n['type'] for n in facts['nodes']};properties=set().union(*(n.keys() for n in facts['nodes']))
    properties.update(set().union(*(e.keys() for edges in facts['relations'].values() for e in edges)))
    terms={k:dict(kind='property',representation=str(ns[k])) for k in properties-{'type','from','to','identity'}}
    terms.update({k:dict(kind='class',representation=str(ns[k])) for k in kinds})
    terms.update({k:dict(kind='relation',representation=str(ns[k])) for k in facts['relations']})
    mapping=dict(mapping_id='ch6-development-local-v1',version='1',backends={n:{'namespace':str(ns)} for n in graphs},term_mappings={n:terms for n in graphs})
    encoding=RdfEdgeEncoding('ch6-dev-v1',str(ns.Edge),str(ns.source),str(ns.target),str(ns.edgeLabel))
    class Local(FusekiClient):
        def _post_query(self,text):
            calls.append(self.backend_id)
            return json.loads(graphs[self.backend_id].query(text).serialize(format='json'))
    sources={n:LogicalSource(n,'development-v1',(n,)) for n in graphs}
    backends={n:SemanticBackend(n,resource,'identity',backend_mapping=mapping,
        profile=replace(default_profile('fuseki'),backend_id=n),rdf_edge_encoding=encoding,
        rdf_node_classes=tuple(str(ns[k]) for k in sorted(kinds))) for n in graphs}
    clients={n:Local(BackendDescriptor(n,'fuseki','sparql','rdf')) for n in graphs}
    return dict(source_schema=public_schema(facts),sources=sources,backends=backends,backend_clients=clients,
        physical_profile=replace(OneShotPolicy.for_mode('performance'),max_parallelism=1)),calls
