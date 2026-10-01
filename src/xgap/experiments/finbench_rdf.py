"""Offline same-facts materialization and fixed-semantics FinBench RDF queries.

Read the verified existing partition, never an answer/measurement artifact. Native
and RDF outputs share an injective technical identity; original source IDs remain
properties. Relationship resources preserve parallel edges and their properties.
"""

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path

from xgap.compilers.rdf_encoding import RdfEdgeEncoding
from xgap.experiments.m15_finbench_partition import (
    ENTITY_PLACEMENTS, RELATIONSHIP_PLACEMENTS, NEO4J_BATCH_FILENAME,
    PARTITION_SCHEMA_VERSION, load_finbench_source_partition, _canonical_sha256,
    _resource_iri, _SCHEMA_IRI, _RESOURCE_IRI,
)
from xgap.experiments.one_shot_records import write_once


SCHEMA = _SCHEMA_IRI
RESOURCE = _RESOURCE_IRI + "one-shot/"
ENCODING = RdfEdgeEncoding("finbench-same-facts-v1",SCHEMA+"Edge",SCHEMA+"source",
    SCHEMA+"target",SCHEMA+"edgeLabel")
ENTITIES = {e.table_id:e for e in ENTITY_PLACEMENTS}
RELATIONS = {e.table_id:e for e in RELATIONSHIP_PLACEMENTS}
FAMILIES = ("f1_direct_transfer_control", "f2_temporal_path_control", "f3_aggregate_risk_ranking")


def local_identity(entity, source_id):
    if entity not in ENTITIES or not isinstance(source_id,str) or not source_id:
        raise ValueError("Expected a known FinBench entity and nonempty text ID")
    # UTF-8 hex is injective, including IDs with slashes, punctuation or Unicode.
    return entity + "_" + source_id.encode("utf-8").hex()


def literal(value):
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is float and math.isfinite(value):
        return json.dumps(repr(value))+"^^<http://www.w3.org/2001/XMLSchema#double>"
    if isinstance(value,str):
        return json.dumps(value,ensure_ascii=False)
    raise ValueError("Unsupported/nonfinite source property")


def _pin(path):
    p=Path(path)
    digest=hashlib.sha256()
    with p.open("rb") as handle:
        for block in iter(lambda:handle.read(1<<20),b""):
            digest.update(block)
    return {"path":p.name,"size_bytes":p.stat().st_size,"sha256":digest.hexdigest()}


def materialize_finbench_rdf(partition_root, output_root):
    """Create a new immutable derivative; original partition is never modified."""
    partition,root=Path(partition_root).resolve(),Path(output_root).resolve()
    original=load_finbench_source_partition(partition)
    if original["schema_version"] != PARTITION_SCHEMA_VERSION:
        raise ValueError("Same-facts materialization requires parameterized v2 input")
    root.mkdir(parents=True,exist_ok=False)
    write_once(root/"intent.json",{"source_partition_sha256":original["partition_sha256"],
        "offline":True,"model_calls":0,"backend_calls":0,"answer_or_cost_reads":0})
    nodes,edges,counts={},set(),{}
    outputs=["graph.ttl","control.ttl",NEO4J_BATCH_FILENAME,"mapping.json"]
    try:
        with (root/"graph.ttl").open("x") as rdf, (root/NEO4J_BATCH_FILENAME).open("x") as native:
            rdf.write(f"@prefix fb: <{SCHEMA}> .\n")
            with (partition/NEO4J_BATCH_FILENAME).open() as batches:
                for line in batches:
                    batch=json.loads(line)
                    claimed=batch.pop("batch_sha256")
                    if claimed != _canonical_sha256(batch):
                        raise ValueError("Source batch hash mismatch")
                    kind,table=batch["kind"],batch["source_table"]
                    for row in batch.get("parameters",{}).get("rows",[]):
                        counts[table]=counts.get(table,0)+1
                        if "xgap_id" in row["props"]:
                            raise ValueError("Technical identity would overwrite an original property")
                        if kind == "nodes":
                            entity=ENTITIES[table]
                            key=(table,row["id"])
                            if key in nodes:
                                raise ValueError("Duplicate entity identity")
                            local=local_identity(*key); uri=RESOURCE+local
                            nodes[key]=uri
                            rdf.write(f"<{uri}> a <{SCHEMA+entity.rdf_type}> ; <{SCHEMA}sourceId> {literal(row['id'])} .\n")
                        elif kind == "relationships":
                            relation=RELATIONS[table]
                            key=row["sourceKey"]
                            if len(key)!=64 or any(c not in "0123456789abcdef" for c in key) or key in edges:
                                raise ValueError("Invalid/duplicate relationship source key")
                            edges.add(key); local="edge_"+key; uri=RESOURCE+local
                            source=nodes[(relation.from_entity,row["fromId"])]
                            target=nodes[(relation.to_entity,row["toId"])]
                            rdf.write(f"<{uri}> a <{SCHEMA}Edge> ; <{SCHEMA}source> <{source}> ; <{SCHEMA}target> <{target}> ; <{SCHEMA}edgeLabel> <{SCHEMA+relation.neo4j_type}> ; <{SCHEMA}sourceKey> {literal(key)} .\n")
                        else:
                            raise ValueError("Unexpected row-bearing batch kind")
                        # Same technical property on native nodes AND relationships.
                        row["props"]["xgap_id"]=local
                        for key,value in sorted(row["props"].items()):
                            rdf.write(f"<{uri}> <{SCHEMA+key}> {literal(value)} .\n")
                    batch["batch_sha256"]=_canonical_sha256(batch)
                    native.write(json.dumps(batch,sort_keys=True,ensure_ascii=False,allow_nan=False)+"\n")
        # Original control serialization is one subject/triple per line; replace
        # only the subject, never string literal contents or predicate meanings.
        aliases={_resource_iri(entity,identifier):uri for (entity,identifier),uri in nodes.items()}
        control_subjects=set()
        with (partition/"load_fuseki.ttl").open() as source, (root/"control.ttl").open("x") as target:
            for line in source:
                if not line.strip() or line.startswith("@prefix "):
                    target.write(line);continue
                old,rest=line.split(" ",1)
                if old not in aliases:
                    raise ValueError("Unknown control entity or changed source serialization")
                uri=aliases[old];target.write(f"<{uri}> {rest}");control_subjects.add(uri)
            for uri in sorted(control_subjects):
                target.write(f"<{uri}> <{SCHEMA}xgap_id> {literal(uri[len(RESOURCE):])} .\n")
        properties={"id":SCHEMA+"sourceId", "xgap_id":SCHEMA+"xgap_id"}
        for e in ENTITY_PLACEMENTS:
            properties.update({c:SCHEMA+c for c in e.neo4j_columns})
            properties.update({predicate:SCHEMA+predicate for _,predicate in e.fuseki_columns})
        for e in RELATIONSHIP_PLACEMENTS:
            properties.update({c:SCHEMA+c for c in e.property_columns})
        labels={e.neo4j_label:SCHEMA+e.rdf_type for e in ENTITY_PLACEMENTS}
        relations={e.neo4j_type:SCHEMA+e.neo4j_type for e in RELATIONSHIP_PLACEMENTS}
        terms={**{k:{"kind":"class","representation":v} for k,v in labels.items()},
               **{k:{"kind":"relation","representation":v} for k,v in relations.items()},
               **{k:{"kind":"property","representation":v} for k,v in properties.items()}}
        mapping={"resource_namespace":RESOURCE,"identity_property":"xgap_id",
            "rdf_edge_encoding":asdict(ENCODING),
            "rdf_node_classes":[SCHEMA+e.rdf_type for e in ENTITY_PLACEMENTS],
            "backend_mapping":{"mapping_id":"finbench-same-facts-v1","version":"1",
                "backends":{backend:{"namespace":SCHEMA} for backend in ("fuseki","rdf_graph","rdf_control")},
                "term_mappings":{backend:terms for backend in ("fuseki","rdf_graph","rdf_control")}}}
        write_once(root/"mapping.json",mapping)
        if load_finbench_source_partition(partition) != original:
            raise ValueError("Source partition changed during preparation")
        receipt={"schema_version":"xgap-finbench-same-facts-rdf-v1","success":True,
            "source_partition_sha256":original["partition_sha256"],"source_archive":original["source_archive"],
            "source_root":str(partition),"entity_count":len(nodes),"relationship_count":len(edges),"table_rows":counts,
            "control_identity_entities":len(control_subjects),"output_files":{p:_pin(root/p) for p in outputs},
            "technical_identity_added":"xgap_id (injective entity type + UTF-8 hex or edge sourceKey)",
            "property_semantics":"same decoded values as native partition; timestamp strings unchanged; floats preserved as xsd:double",
            "offline":True,"model_calls":0,"backend_calls":0,"answer_or_cost_reads":0,"paper_result":False}
        write_once(root/"manifest.json",receipt)
        return receipt
    except Exception as error:
        write_once(root/"failure.json",{"success":False,"error_type":type(error).__name__,"error":str(error)})
        raise


def _edge(name,source,relation,target):
    return f"?{name} a fb:Edge ; fb:source {source} ; fb:target {target} ; fb:edgeLabel fb:{relation} ."


def fixed_semantics_query(family, parameters):
    """Canonical public query for the agreed family, no engine-specific rewrite.

    All sources are unresolved: no SERVICE, source assignments or answer rows.
    This is for fixed-semantics evaluation/gold, never supplied as an NL prediction.
    """
    p=dict(parameters)
    required=({"person_id","start_time","end_time"} if family==FAMILIES[0] else
              {"start_account_id","start_time","end_time","max_hops"} if family==FAMILIES[1] else
              {"start_time","end_time","risk_level","top_k"} if family==FAMILIES[2] else None)
    if required is None or set(p)!=required:
        raise ValueError("Unexpected family parameter contract")
    if not all(isinstance(p[k],str) and p[k] for k in required-{"max_hops","top_k"}):
        raise ValueError("Expected nonempty text parameters")
    start,end=literal(p["start_time"]),literal(p["end_time"])
    prefix=f"PREFIX fb: <{SCHEMA}>\n"
    if family==FAMILIES[0]:
        return prefix+f'''SELECT ?company_id ?account_id (ROUND(SUM(?amount)*1000)/1000 AS ?total_amount) WHERE {{
?person a fb:Person ; fb:sourceId {literal(p['person_id'])} .
{_edge('own_p','?person','OWNS_ACCOUNT','?source')}
{_edge('transfer','?source','TRANSFERRED_TO','?account')}
{_edge('own_c','?company','OWNS_ACCOUNT','?account')}
?company a fb:Company ; fb:sourceId ?company_id .
?source a fb:Account . ?account a fb:Account ; fb:sourceId ?account_id ; fb:isBlocked true .
?transfer fb:createTime ?time ; fb:amount ?amount .
FILTER(?time >= {start} && ?time <= {end})
}} GROUP BY ?company_id ?account_id ORDER BY ?company_id ?account_id'''
    if family==FAMILIES[1]:
        if type(p['max_hops']) is not int or p['max_hops']!=3:
            raise ValueError("The agreed temporal family has max_hops=3")
        branches=[]
        for hops in range(1,4):
            nodes=['?start']+[f'?v{i}' for i in range(1,hops)]+['?other']
            parts=[]; predicates=[]
            for i in range(hops):
                parts += [_edge(f'e{i}',nodes[i],'TRANSFERRED_TO',nodes[i+1]),f'?e{i} fb:createTime ?t{i} .']
                predicates += [f'?t{i} >= {start}',f'?t{i} <= {end}']
                if i: predicates.append(f'?t{i-1} < ?t{i}')
            predicates += [f'{a} != {b}' for i,a in enumerate(nodes) for b in nodes[i+1:]]
            parts += ['FILTER('+' && '.join(predicates)+')',f'BIND({hops} AS ?account_distance)']
            branches.append('{ '+'\n'.join(parts)+' }')
        return prefix+f'''SELECT DISTINCT ?other_id ?account_distance ?medium_id ?medium_type WHERE {{
?start a fb:Account ; fb:sourceId {literal(p['start_account_id'])} .
{{ {' UNION '.join(branches)} }}
?other a fb:Account ; fb:sourceId ?other_id .
{_edge('signin','?medium','SIGNED_IN_TO','?other')}
?medium a fb:Medium ; fb:sourceId ?medium_id ; fb:isBlocked true ; fb:mediumType ?medium_type .
}} ORDER BY ?account_distance ?other_id ?medium_id'''
    if type(p['top_k']) is not int or not 1<=p['top_k']<=1000:
        raise ValueError("Top K must be a bounded positive integer")
    return prefix+f'''SELECT ?company_id (ROUND(SUM(?amount)*1000)/1000 AS ?total_amount) WHERE {{
{{ SELECT DISTINCT ?company ?company_id ?account WHERE {{
?company a fb:Company ; fb:sourceId ?company_id . ?account a fb:Account .
{_edge('own','?company','OWNS_ACCOUNT','?account')}
{_edge('signin','?medium','SIGNED_IN_TO','?account')}
?medium a fb:Medium ; fb:riskLevel {literal(p['risk_level'])} .
}} }}
{_edge('transfer','?source','TRANSFERRED_TO','?account')}
?transfer fb:createTime ?time ; fb:amount ?amount .
FILTER(?time >= {start} && ?time < {end})
}} GROUP BY ?company_id ORDER BY DESC(?total_amount) ?company_id LIMIT {p['top_k']}'''
