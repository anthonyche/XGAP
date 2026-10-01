"""Bounded conversion of frozen financial facts to 32 real mixed-source loads.

Each transfer is stored only at its owner bank. Local copies of endpoint accounts
carry properties read from the canonical account rows, not regenerated properties.
A one-byte-per-account disk mmap and one endpoint bitmap replace graph-sized
Python dictionaries/sets. This module does not start services or run queries.
"""
from contextlib import contextmanager
from dataclasses import asdict
import gzip
import hashlib
import json
import mmap
from pathlib import Path
import shutil
import time

from xgap.compilers.rdf_encoding import RdfEdgeEncoding
from xgap.experiments.ch6_financial_scale import (
    ACCOUNT_FIELDS, TRANSFER_FIELDS, BANKS, DEGREE, GIB, MAX_CHUNKS,
    START_MS, VERSION as CANONICAL_VERSION, WINDOW_MS,
)
from xgap.experiments.ch6_materialize import NS, RESOURCE, identity


VERSION = 'xgap-financial-mixed-loads-v1'
RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
XSD = 'http://www.w3.org/2001/XMLSchema#'
NODE_HEADER = b'xgap_id:ID,id,isBlocked:boolean,:LABEL\r\n'
EDGE_HEADER = b':START_ID,:END_ID,:TYPE,xgap_id,id,timestamp:long,amount:long\r\n'


def pin(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            digest.update(block)
    return dict(path=str(path.resolve()), bytes=path.stat().st_size, sha256=digest.hexdigest())


def _json(path, value, budget=None):
    data = (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()
    if budget:
        budget.consume(len(data))
    with Path(path).open('xb') as stream:
        stream.write(data)


def _relative(root, path):
    candidate = Path(path)
    if candidate.is_absolute() or '..' in candidate.parts:
        raise ValueError('Canonical chunk must stay inside its root')
    full = root/candidate
    if full.is_symlink() or not full.is_file() or not full.resolve().is_relative_to(root):
        raise ValueError('Canonical chunk is missing or escapes its root')
    return full


def _header(fields):
    return (','.join(fields)+'\n').encode()


def _rows(root, chunk, digest):
    """Verify compressed and decoded content while consuming a bounded row stream."""
    path = _relative(root, chunk['path'])
    actual = pin(path)
    if any(actual[k] != chunk[k] for k in ('bytes', 'sha256')):
        raise ValueError('Canonical compressed chunk changed: '+chunk['path'])
    fields = ACCOUNT_FIELDS if chunk['kind'] == 'accounts' else TRANSFER_FIELDS
    decoded = hashlib.sha256(); size = 0; count = 0
    with gzip.open(path, 'rb') as stream:
        first = stream.readline(512)
        if first != _header(fields):
            raise ValueError('Canonical CSV header differs')
        decoded.update(first); size += len(first)
        while line := stream.readline(1025):
            if len(line) > 1024 or not line.endswith(b'\n'):
                raise ValueError('Canonical row exceeds fixed financial schema')
            decoded.update(line); size += len(line); digest.update(line); count += 1
            # This frozen generator only emits fixed ASCII identifiers, decimal
            # integers and booleans. Reject CSV quoting instead of ambiguously
            # parsing commas/newlines inside a field.
            text = line[:-1].decode('ascii')
            if '"' in text or '\n' in text or '\r' in text:
                raise ValueError('Unexpected quoted/multiline canonical value')
            row = text.split(',')
            if len(row) != len(fields):
                raise ValueError('Wrong canonical field count')
            yield row
    if (count != chunk['rows'] or size != chunk['decoded_bytes']
            or decoded.hexdigest() != chunk['decoded_sha256']):
        raise ValueError('Canonical decoded chunk changed: '+chunk['path'])


class _Budget:
    def __init__(self, root, maximum, reserve):
        self.root = root; self.maximum = maximum; self.reserve = reserve; self.used = 0
        self.next_check = 0

    def consume(self, size):
        if self.used+size > self.maximum:
            raise ValueError('Materialization output byte limit reached')
        self.used += size
        if self.used >= self.next_check:
            if shutil.disk_usage(self.root).free < self.reserve+size:
                raise ValueError('Materialization disk reserve reached')
            self.next_check = self.used+8*1024**2


class _Sink:
    def __init__(self, stream, budget):
        self.stream = stream; self.budget = budget

    def write(self, data):
        self.budget.consume(len(data)); return self.stream.write(data)

    def flush(self):
        self.stream.flush()


@contextmanager
def _compressed(path, budget):
    with Path(path).open('xb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=_Sink(raw, budget),
                           mtime=0, compresslevel=1) as stream:
            yield stream


def _iri(business):
    return '<'+RESOURCE+identity(business)+'>'


def _node_rdf(business, blocked):
    local = identity(business); subject = '<'+RESOURCE+local+'>'
    return (f'{subject} <{RDF_TYPE}> <{NS}Account> .\n'
            f'{subject} <{NS}id> "{business}" .\n'
            f'{subject} <{NS}xgap_id> "{local}" .\n'
            f'{subject} <{NS}isBlocked> "{blocked}"^^<{XSD}boolean> .\n').encode()


def _edge_rdf(ident, source, target, amount, timestamp):
    local = identity('TRANSFERRED_TO:'+ident); subject = '<'+RESOURCE+local+'>'
    return (f'{subject} <{RDF_TYPE}> <{NS}Edge> .\n'
            f'{subject} <{NS}source> {_iri(source)} .\n'
            f'{subject} <{NS}target> {_iri(target)} .\n'
            f'{subject} <{NS}edgeLabel> <{NS}TRANSFERRED_TO> .\n'
            f'{subject} <{NS}id> "{ident}" .\n'
            f'{subject} <{NS}xgap_id> "{local}" .\n'
            f'{subject} <{NS}amount> "{amount}"^^<{XSD}integer> .\n'
            f'{subject} <{NS}timestamp> "{timestamp}"^^<{XSD}integer> .\n').encode()


def _mark(bitmap, ordinal):
    bitmap[ordinal >> 3] |= 1 << (ordinal & 7)


def _marked(bitmap):
    for byte_index, value in enumerate(bitmap):
        while value:
            bit = value & -value
            yield byte_index*8+bit.bit_length()-1
            value ^= bit


def _chunks(manifest, count):
    result = {kind: {bank: [] for bank in range(BANKS)} for kind in ('accounts', 'transfers')}
    entries = manifest['chunks']
    if not entries or len(entries) > MAX_CHUNKS:
        raise ValueError('Canonical chunk count exceeds declared bound')
    names = set()
    for chunk in entries:
        if chunk['path'] in names or chunk['kind'] not in result or type(chunk['owner_bank']) is not int or not 0 <= chunk['owner_bank'] < BANKS:
            raise ValueError('Duplicate or invalid canonical chunk')
        names.add(chunk['path']); result[chunk['kind']][chunk['owner_bank']].append(chunk)
    for kind in result:
        for bank, group in result[kind].items():
            group.sort(key=lambda c: c['first_bank_row']); at = 0
            for chunk in group:
                if chunk['first_bank_row'] != at or type(chunk['rows']) is not int or chunk['rows'] <= 0:
                    raise ValueError('Canonical chunk coverage has gap or overlap')
                at += chunk['rows']
            if at != count*(DEGREE if kind == 'transfers' else 1):
                raise ValueError('Canonical bank row count differs')
    return result


def _mapping(source_ids):
    terms = {k: dict(kind='property', representation=NS+k)
             for k in ('id', 'xgap_id', 'isBlocked', 'amount', 'timestamp')}
    terms['Account'] = dict(kind='class', representation=NS+'Account')
    terms['TRANSFERRED_TO'] = dict(kind='relation', representation=NS+'TRANSFERRED_TO')
    return dict(resource_namespace=RESOURCE, identity_property='xgap_id',
        rdf_edge_encoding=asdict(RdfEdgeEncoding('ch6-financial-v1', NS+'Edge', NS+'source', NS+'target', NS+'edgeLabel')),
        rdf_node_classes=[NS+'Account'], backend_mapping=dict(mapping_id='ch6-financial-v1', version='1',
            backends={s: dict(namespace=NS) for s in source_ids}, term_mappings={s: terms for s in source_ids}))


def materialize(canonical_root, output, *, canonical_manifest_sha256=None, execute=False,
                source_count=32, max_output_bytes=64*GIB, reserve_bytes=6*GIB,
                progress=None):
    """Convert all frozen canonical facts once; a failure retains partial output.

    Default is a no-write plan. Only the requested 32-source calibration layout
    is admitted here; source-count sweeps are a separate experimental action.
    """
    canonical = Path(canonical_root).expanduser().resolve(); root = Path(output).expanduser().resolve()
    if type(source_count) is not int or source_count != 32 or type(execute) is not bool:
        raise ValueError('This calibration requires exactly 32 sources')
    if any(type(v) is not int for v in (max_output_bytes, reserve_bytes)) or max_output_bytes < 1 or reserve_bytes < 0:
        raise ValueError('Explicit positive output cap and nonnegative reserve required')
    manifest_pin = pin(canonical/'manifest.json')
    if canonical_manifest_sha256 is not None and manifest_pin['sha256'] != canonical_manifest_sha256:
        raise ValueError('Canonical manifest hash differs')
    if execute and canonical_manifest_sha256 is None:
        raise ValueError('Execute requires the frozen canonical manifest SHA-256')
    manifest = json.loads((canonical/'manifest.json').read_text())
    if manifest.get('schema_version') != CANONICAL_VERSION or not manifest.get('success'):
        raise ValueError('Successful canonical financial manifest required')
    per_bank = manifest['recipe']['nodes_per_bank']; nodes = per_bank*BANKS; edges = nodes*DEGREE
    if type(per_bank) is not int or not 9 <= per_bank <= 312500 or manifest['counts']['accounts'] != nodes or manifest['counts']['logical_edges'] != edges:
        raise ValueError('Invalid frozen canonical graph domain')
    chunks = _chunks(manifest, per_bank)
    planned = dict(schema_version=VERSION, executed=False, canonical_manifest=manifest_pin,
        logical_facts_sha256=manifest['logical_facts_sha256'], output=str(root), source_count=32,
        logical_nodes=nodes, logical_edges=edges, physical_neo4j_relationships=edges//2,
        memory_contract=dict(account_mmap_bytes=nodes, endpoint_bitmap_bytes=(nodes+7)//8,
            account_index_origin='actual verified canonical Account rows; not regenerated properties'),
        model_calls=0, backend_calls=0, query_calls=0, services_prepared=False)
    if not execute:
        return planned
    if root.exists() or root == canonical or canonical.is_relative_to(root):
        raise ValueError('New separate materialization directory required; no implicit resume')
    parent = root.parent
    while not parent.exists():
        parent = parent.parent
    if shutil.disk_usage(parent).free < max_output_bytes+reserve_bytes:
        raise ValueError('Insufficient space for output cap plus reserve')
    root.mkdir(parents=True, exist_ok=False); started = time.perf_counter()
    budget = _Budget(root, max_output_bytes, reserve_bytes)
    _json(root/'intent.json', planned, budget)
    sources = []; digests = {k: hashlib.sha256(_header(f)) for k, f in (('accounts', ACCOUNT_FIELDS), ('transfers', TRANSFER_FIELDS))}
    properties_path = root/'verified-account-properties.bin'
    try:
        budget.consume(nodes)
        with properties_path.open('x+b') as storage:
            storage.truncate(nodes)
            with mmap.mmap(storage.fileno(), nodes, access=mmap.ACCESS_WRITE) as properties:
                ordinal = 0
                for bank in range(BANKS):
                    for chunk in chunks['accounts'][bank]:
                        for ident, kind, owner, blocked in _rows(canonical, chunk, digests['accounts']):
                            if (ident != f'account:{ordinal:010d}' or kind != 'Account'
                                    or owner != str(bank) or blocked not in ('true', 'false')):
                                raise ValueError('Canonical account identity/type/property differs')
                            properties[ordinal] = 2 if blocked == 'true' else 1; ordinal += 1
                if ordinal != nodes or digests['accounts'].hexdigest() != manifest['canonical_digests']['accounts']:
                    raise ValueError('Canonical account digest/count differs')
                properties.flush()
                edge_ordinal = 0
                for bank in range(BANKS):
                    engine = 'neo4j' if bank < 16 else 'rdf'; source_id = f'{engine}-{bank:02d}'
                    directory = root/source_id; directory.mkdir(); bitmap = bytearray((nodes+7)//8)
                    for n in range(bank*per_bank, (bank+1)*per_bank):
                        _mark(bitmap, n)
                    edge_path = directory/('relationships.csv.gz' if engine == 'neo4j' else 'data.nt.gz')
                    local_edges = 0; materialized_nodes = 0; decoded_bytes = 0
                    with _compressed(edge_path, budget) as edge_stream:
                        if engine == 'neo4j':
                            edge_stream.write(EDGE_HEADER); decoded_bytes += len(EDGE_HEADER)
                        for chunk in chunks['transfers'][bank]:
                            for row in _rows(canonical, chunk, digests['transfers']):
                                ident, kind, source, target, owner, source_bank, target_bank, amount, timestamp = row
                                a = int(source[8:]); b = int(target[8:]); stamp = int(timestamp); value = int(amount)
                                if (ident != f'transfer:{edge_ordinal:012d}' or kind != 'TRANSFERRED_TO'
                                    or source != f'account:{a:010d}' or target != f'account:{b:010d}'
                                    or not 0 <= a < nodes or not 0 <= b < nodes or a == b
                                    or owner != str(bank) or source_bank != str(bank) or a//per_bank != bank
                                    or target_bank != str(b//per_bank) or not 1 <= value <= 1000000
                                    or not START_MS <= stamp < START_MS+WINDOW_MS
                                    or not properties[a] or not properties[b]):
                                    raise ValueError('Invalid canonical transfer or absent endpoint')
                                _mark(bitmap, a); _mark(bitmap, b)
                                if engine == 'neo4j':
                                    block = (','.join((identity(source), identity(target), kind,
                                        identity(kind+':'+ident), ident, timestamp, amount))+'\r\n').encode()
                                else:
                                    block = _edge_rdf(ident, source, target, amount, timestamp)
                                edge_stream.write(block); decoded_bytes += len(block)
                                local_edges += 1; edge_ordinal += 1
                        if engine == 'rdf':
                            for n in _marked(bitmap):
                                block = _node_rdf(f'account:{n:010d}', 'true' if properties[n] == 2 else 'false')
                                edge_stream.write(block); decoded_bytes += len(block); materialized_nodes += 1
                    source = dict(source_id=source_id, engine=engine, atoms=[bank],
                        logical_edges=local_edges, owned_accounts=per_bank,
                        endpoint_node_properties='verified actual canonical values',
                        temporal_view_copies=0, decoded_input_bytes=decoded_bytes)
                    if engine == 'neo4j':
                        node_path = directory/'nodes-Account.csv.gz'
                        with _compressed(node_path, budget) as node_stream:
                            node_stream.write(NODE_HEADER); source['decoded_input_bytes'] += len(NODE_HEADER)
                            for n in _marked(bitmap):
                                business = f'account:{n:010d}'; blocked = 'true' if properties[n] == 2 else 'false'
                                block = f'{identity(business)},{business},{blocked},Account\r\n'.encode()
                                node_stream.write(block); source['decoded_input_bytes'] += len(block); materialized_nodes += 1
                        source['native_bulk_files'] = {node_path.name: pin(node_path), edge_path.name: pin(edge_path)}
                        source['physical_neo4j_relationships'] = local_edges
                        source['rdf_triples'] = 0
                    else:
                        source['rdf_load'] = pin(edge_path)
                        source['physical_neo4j_relationships'] = 0
                        source['rdf_triples'] = local_edges*8+materialized_nodes*4
                    source.update(materialized_nodes=materialized_nodes, endpoint_copies=materialized_nodes-per_bank)
                    source['compressed_input_bytes'] = sum(p['bytes'] for p in source.get('native_bulk_files', {}).values()) + source.get('rdf_load', {}).get('bytes', 0)
                    _json(directory/'receipt.json', dict(schema_version=VERSION, success=True, **source), budget)
                    sources.append(source)
                    if progress:
                        progress(dict(phase='materialize', source_id=source_id, logical_edges=local_edges,
                            sources_completed=len(sources), elapsed_seconds=time.perf_counter()-started))
                if edge_ordinal != edges or digests['transfers'].hexdigest() != manifest['canonical_digests']['transfers']:
                    raise ValueError('Canonical transfer digest/count differs')
        if pin(canonical/'manifest.json') != manifest_pin:
            raise ValueError('Canonical manifest changed during conversion')
        mapping = _mapping([s['source_id'] for s in sources]); _json(root/'mapping.json', mapping, budget)
        schema = {s['source_id']: dict(nodes={'Account': dict(properties=['id', 'xgap_id', 'isBlocked'])},
            edges=[dict(label='TRANSFERRED_TO', source='Account', target='Account', properties=['id', 'xgap_id', 'amount', 'timestamp'])],
            owner_banks=s['atoms'], endpoint_copies=s['endpoint_copies']) for s in sources}
        schema.update(shared_identity_namespace=RESOURCE, identity_property='xgap_id',
            scalar_semantics=dict(id='string', isBlocked='boolean', amount='integer cents', timestamp='integer UTC milliseconds'),
            endpoint_replication='Only nodes needed by local edges plus owner nodes; each logical edge belongs to exactly one source')
        _json(root/'source-schema.json', schema, budget)
        receipt = dict(planned, executed=True, success=True, sources=sources,
            mapping=pin(root/'mapping.json'), source_schema=pin(root/'source-schema.json'),
            property_index=pin(properties_path), canonical_digests={k: d.hexdigest() for k, d in digests.items()},
            logical_edge_rows_emitted=sum(s['logical_edges'] for s in sources),
            physical_neo4j_relationships=sum(s['physical_neo4j_relationships'] for s in sources),
            rdf_triples=sum(s['rdf_triples'] for s in sources),
            materialized_node_copies=sum(s['materialized_nodes'] for s in sources),
            additional_endpoint_copies=sum(s['endpoint_copies'] for s in sources),
            compressed_input_bytes=sum(s['compressed_input_bytes'] for s in sources),
            decoded_input_bytes=sum(s['decoded_input_bytes'] for s in sources),
            offline_seconds=time.perf_counter()-started,
            backend_store_bytes=None, max_output_bytes=max_output_bytes, reserve_bytes=reserve_bytes)
        _json(root/'receipt.json', receipt, budget)
        return receipt
    except BaseException as error:
        _json(root/'failure.json', dict(schema_version=VERSION, success=False,
            error_type=type(error).__name__, error=str(error), completed_sources=len(sources),
            partial_inputs_preserved=True, automatic_retries=0))
        raise
