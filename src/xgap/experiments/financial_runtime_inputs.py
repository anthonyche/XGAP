"""Pinned financial source inputs shared by portable workers and reference checks."""
from dataclasses import replace
import json
import hashlib
from pathlib import Path

from xgap.experiments import ch6_financial_materialize as canonical_rows
from xgap.experiments.one_shot_profile import read_pinned, _backend


def load(pin_value):
    return json.loads(read_pinned(pin_value['path'], pin_value['sha256']))


def runtime_inputs(materialized):
    """Freeze the shared analytic source-count estimator before any query runs."""
    from xgap.compilers.features import default_profile
    from xgap.planning.runtime_estimator import SourceStatistics, FrozenSourceStatistics
    from xgap.planning.relative_source_work import FrozenSourceWorkRanker
    from xgap.runtime.semantic_planning import LogicalSource
    mapping=load(materialized['mapping']); schema=load(materialized['source_schema'])
    version=materialized['logical_facts_sha256']; sources={}; backends={}; entries=[]; populations=[]
    for item in materialized['sources']:
        sid=item['source_id']; nodes=item['materialized_nodes']; edges=item['logical_edges']
        engine='neo4j' if item['engine']=='neo4j' else 'fuseki'
        raw=(dict(mapping) if engine=='fuseki' else
             {k:mapping[k] for k in ('resource_namespace','identity_property')})
        raw['profile']=replace(default_profile(engine),backend_id=sid).to_dict()
        backends[sid]=_backend(raw,sid)
        sources[sid]=LogicalSource(sid,version,(sid,))
        entries.append(SourceStatistics(sid,sid,version,nodes+edges,None,materialized['canonical_manifest']['sha256']))
        populations.append((sid,nodes,edges))
    estimator=FrozenSourceWorkRanker(FrozenSourceStatistics('financial-counts-v1',version,tuple(entries)),
        tuple(populations),('id','xgap_id'),materialized['canonical_manifest']['sha256'],distinct_binding_keys=True)
    return schema,sources,backends,estimator


def checked_canonical_stream(root, manifest, kind):
    """Yield verified canonical tuples; reference consumers exhaust every pass.

    Reuse ingest's compressed/decoded/hash/count checks and bounded row parser.
    The global digest includes one header and bank-ordered row bytes, matching
    generation; its final check precedes publishing any reference answers.
    """
    if kind not in ('accounts', 'transfers'):
        raise ValueError('Canonical reference stream kind must be accounts or transfers')
    root = Path(root).resolve()
    chunks = canonical_rows._chunks(manifest, manifest['recipe']['nodes_per_bank'])
    fields = canonical_rows.ACCOUNT_FIELDS if kind == 'accounts' else canonical_rows.TRANSFER_FIELDS
    digest = hashlib.sha256(canonical_rows._header(fields)); count = 0
    for bank in range(canonical_rows.BANKS):
        for chunk in chunks[kind][bank]:
            for row in canonical_rows._rows(root, chunk, digest):
                count += 1
                if kind == 'accounts':
                    yield row[0], row[1], int(row[2]), row[3]
                else:
                    yield (*row[:4], *(int(value) for value in row[4:]))
    count_key = 'accounts' if kind == 'accounts' else 'logical_edges'
    if count != manifest['counts'][count_key] or digest.hexdigest() != manifest['canonical_digests'][kind]:
        raise ValueError('Canonical reference global count/digest differs: '+kind)
