"""Offline canonical financial stress data; no services, queries, or model calls.

The 32 owner banks are immutable atomic shards. Endpoint references do not copy
accounts, and source layouts change only the grouping of atoms. This is an
authored deterministic financial graph, not the FinBench generator/distribution.
"""
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import resource
import shutil
import sys
import time


VERSION = 'xgap-financial-owner-banks-v1'
BANKS = 32
DEGREE = 10
NODES_PER_BANK = 312500
SEED = 20260928
SOURCE_COUNTS = (2, 4, 8, 16, 32)
GIB = 1024**3
MAX_CHUNKS = 100000
ACCOUNT_FIELDS = ('id', 'type', 'owner_bank', 'isBlocked')
TRANSFER_FIELDS = ('id', 'type', 'source', 'target', 'owner_bank', 'source_bank',
                   'target_bank', 'amount', 'timestamp')
START_MS = 1704067200000  # 2024-01-01T00:00:00Z.
WINDOW_MS = 366 * 24 * 60 * 60 * 1000


def _validate(nodes_per_bank, seed=SEED):
    if type(nodes_per_bank) is not int or not 9 <= nodes_per_bank <= NODES_PER_BANK:
        raise ValueError('Each of 32 banks needs 9..312500 accounts')
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError('Seed must be an unsigned 64-bit integer')


def source_layout(source_count, *, nodes_per_bank=NODES_PER_BANK):
    """Group disjoint atoms, never merge Neo4j and RDF into the same source."""
    _validate(nodes_per_bank)
    if type(source_count) is not int or source_count not in SOURCE_COUNTS:
        raise ValueError('Source count must be 2, 4, 8, 16, or 32')
    per_engine = source_count // 2
    width = 16 // per_engine
    sources = []
    for engine, start in (('neo4j', 0), ('rdf', 16)):
        for i in range(per_engine):
            atoms = list(range(start + i * width, start + (i + 1) * width))
            sources.append(dict(source_id=f'{engine}-{i:02d}', engine=engine,
                                atoms=atoms, accounts=len(atoms)*nodes_per_bank,
                                logical_edges=len(atoms)*nodes_per_bank*DEGREE))
    return dict(source_count=source_count, sources=sources,
                additional_control_sources=0, logical_facts_unchanged=True)


def recipe(*, nodes_per_bank=NODES_PER_BANK, seed=SEED, chunk_rows=100000):
    _validate(nodes_per_bank, seed)
    if type(chunk_rows) is not int or not 1 <= chunk_rows <= 1000000:
        raise ValueError('Chunk rows must be 1..1000000')
    files = BANKS * (math.ceil(nodes_per_bank/chunk_rows)
                    + math.ceil(nodes_per_bank*DEGREE/chunk_rows))
    if files > MAX_CHUNKS:
        raise ValueError('Chunk manifest would exceed its fixed 100000-file bound')
    nodes = BANKS * nodes_per_bank
    edges = nodes * DEGREE
    # Conservative bounds for these fixed ASCII CSV schemas, not a compressed
    # storage estimate. Include gzip framing, chunk metadata, and final receipts.
    raw_bound = nodes*256 + edges*512
    output_bound = raw_bound + raw_bound//100 + files*4096 + 1024**2
    return dict(schema_version=VERSION, synthetic=True, benchmark_equivalence=False,
        seed=seed, atomic_shards=BANKS, nodes_per_bank=nodes_per_bank,
        counts=dict(accounts=nodes, logical_edges=edges, intra_bank_edges=nodes*8,
                    inter_bank_edges=nodes*2, out_degree=DEGREE),
        atom_counts=dict(accounts=nodes_per_bank, logical_edges=nodes_per_bank*DEGREE),
        core=dict(node_type='Account', relation='TRANSFERRED_TO', measure='amount',
                  control='isBlocked', target_type='Account'),
        fields=dict(accounts=list(ACCOUNT_FIELDS), transfers=list(TRANSFER_FIELDS)),
        units=dict(amount='integer cents; not asserted equal to historical D3 amount units',
                   timestamp='integer UTC milliseconds since Unix epoch'),
        generation=dict(ownership='source account bank owns each transfer exactly once',
            slots='0..7 intra-bank; 8..9 in two distinct other banks; no self-loops or repeated destinations per account',
            destinations='SHA-256 modulo domain with bounded collision skipping; slots 0,1,8 target first max(3,ceil(bank_size/20)) accounts; other slots target full bank',
            distribution='explicit hot-prefix rule; not a power law or empirical FinBench distribution',
            amount_cents='1..1000000 from edge SHA-256',
            timestamp=dict(start_inclusive_ms=START_MS, end_exclusive_ms=START_MS+WINDOW_MS),
            isBlocked='account SHA-256 modulo 100 equals 0; approximately 1%, not forced exact',
            facts_depend_on=['version', 'seed', 'nodes_per_bank'],
            facts_independent_of=['chunk_rows', 'source_count', 'queries', 'answers', 'method_results']),
        representation=dict(canonical_only=True, endpoint_replication=False,
            temporal_view_copies=0, physical_neo4j_relationships=None, rdf_triples=None,
            note='One canonical row per logical edge; backend encodings and loads are not implemented here'),
        chunk_rows=chunk_rows, maximum_chunks=MAX_CHUNKS, expected_chunks=files,
        uncompressed_row_bytes_upper_bound=raw_bound,
        output_bytes_upper_bound=output_bound,
        memory_contract=dict(buffered_rows=1, per_account_destination_set_max=10,
                             chunk_metadata_entries_max=MAX_CHUNKS),
        layouts=[source_layout(s, nodes_per_bank=nodes_per_bank) for s in SOURCE_COUNTS],
        model_calls=0, backend_calls=0, query_calls=0, jobs_submitted=0,
        formal_workload_admitted=False, services_prepared=False)


def _digest(seed, bank, local, slot):
    return hashlib.sha256(f'{VERSION}:{seed}:{bank}:{local}:{slot}'.encode('ascii')).digest()


def _account_id(bank, local, nodes_per_bank):
    return f'account:{bank*nodes_per_bank+local:010d}'


def iter_accounts(bank, *, nodes_per_bank=NODES_PER_BANK, seed=SEED):
    _validate(nodes_per_bank, seed)
    if type(bank) is not int or not 0 <= bank < BANKS:
        raise ValueError('Invalid owner bank')
    for local in range(nodes_per_bank):
        blocked = int.from_bytes(_digest(seed, bank, local, 'account')[:8], 'big') % 100 == 0
        yield (_account_id(bank, local, nodes_per_bank), 'Account', bank,
               'true' if blocked else 'false')


def iter_transfers(bank, *, nodes_per_bank=NODES_PER_BANK, seed=SEED):
    _validate(nodes_per_bank, seed)
    if type(bank) is not int or not 0 <= bank < BANKS:
        raise ValueError('Invalid owner bank')
    hot_size = max(3, (nodes_per_bank + 19)//20)
    for local in range(nodes_per_bank):
        used = {local}
        first_shift = None
        for slot in range(DEGREE):
            h = _digest(seed, bank, local, slot)
            target_bank = bank
            if slot == 8:
                first_shift = 1 + int.from_bytes(h[24:], 'big') % 31
                target_bank = (bank + first_shift) % BANKS
            elif slot == 9:
                shift = 1 + (first_shift + int.from_bytes(h[24:], 'big') % 30) % 31
                target_bank = (bank + shift) % BANKS
            domain = hot_size if slot in (0, 1, 8) else nodes_per_bank
            target = int.from_bytes(h[:8], 'big') % domain
            if slot < 8:
                # At most eight forbidden indices; domain has enough available
                # targets. This is bounded work, not graph-wide rejection search.
                while target in used:
                    target = (target + 1) % domain
                used.add(target)
            ordinal = (bank*nodes_per_bank+local)*DEGREE+slot
            yield (f'transfer:{ordinal:012d}', 'TRANSFERRED_TO',
                   _account_id(bank, local, nodes_per_bank),
                   _account_id(target_bank, target, nodes_per_bank), bank, bank, target_bank,
                   1 + int.from_bytes(h[8:16], 'big') % 1000000,
                   START_MS + int.from_bytes(h[16:24], 'big') % WINDOW_MS)



FIELD_SCHEMA = {
    'accounts': (
        ('id', 'string', 'identifier'), ('type', 'string', 'node_type'),
        ('owner_bank', 'integer', 'partition'), ('isBlocked', 'boolean', 'semantic_attribute')),
    'transfers': (
        ('id', 'string', 'identifier'), ('type', 'string', 'relation_type'),
        ('source', 'string', 'topology'), ('target', 'string', 'topology'),
        ('owner_bank', 'integer', 'partition'), ('source_bank', 'integer', 'partition'),
        ('target_bank', 'integer', 'partition'), ('amount', 'integer', 'semantic_attribute'),
        ('timestamp', 'integer', 'semantic_attribute')),
}


class _GraphStatistics:
    """Fixed-size counters over actual emitted rows, independent of target size."""
    def __init__(self):
        self.nodes = self.edges = self.blocked = 0
        self.node_banks = [0]*BANKS
        self.edge_banks = [0]*BANKS
        self.intra_bank = self.cross_engine = 0
        self.cross_source = [0]*len(SOURCE_COUNTS)
        self.amount_min = self.amount_max = None
        self.timestamp_min = self.timestamp_max = None

    def observe(self, kind, row):
        # CSV serialization is not a type checker. Validate every generated
        # field before counting it; all validated columns are total/non-null.
        fields = FIELD_SCHEMA[kind]
        if len(row) != len(fields):
            raise ValueError('Generated row has wrong column count')
        for value, (_, typ, _) in zip(row, fields):
            if ((typ == 'integer' and type(value) is not int)
                or (typ == 'boolean' and value not in ('true', 'false'))
                or (typ == 'string' and (type(value) is not str or not value))):
                raise ValueError('Generated row has invalid type or missing value')
        if kind == 'accounts':
            if row[1] != 'Account' or not 0 <= row[2] < BANKS:
                raise ValueError('Generated account type/owner mismatch')
            self.nodes += 1
            self.node_banks[row[2]] += 1
            self.blocked += row[3] == 'true'
        else:
            _, label, source, target, owner, source_bank, target_bank, amount, timestamp = row
            if (label != 'TRANSFERRED_TO' or owner != source_bank
                    or not 0 <= owner < BANKS or not 0 <= target_bank < BANKS
                    or source == target or not 1 <= amount <= 1000000
                    or not START_MS <= timestamp < START_MS+WINDOW_MS):
                raise ValueError('Generated transfer schema/domain mismatch')
            self.edges += 1
            self.edge_banks[owner] += 1
            self.intra_bank += source_bank == target_bank
            self.cross_engine += (source_bank < 16) != (target_bank < 16)
            # Every bank owns a contiguous group at each S; works for both
            # engines because bank16 starts the RDF half. Five fixed counters.
            if source_bank != target_bank:
                for i, width in enumerate((16, 8, 4, 2, 1)):
                    self.cross_source[i] += source_bank//width != target_bank//width
            self.amount_min = amount if self.amount_min is None else min(self.amount_min, amount)
            self.amount_max = amount if self.amount_max is None else max(self.amount_max, amount)
            self.timestamp_min = timestamp if self.timestamp_min is None else min(self.timestamp_min, timestamp)
            self.timestamp_max = timestamp if self.timestamp_max is None else max(self.timestamp_max, timestamp)

    def result(self, chunks):
        node_fields = [dict(name=n, type=t, role=r, non_null_values=self.nodes,
                            type_valid_values=self.nodes, null_values=0) for n,t,r in FIELD_SCHEMA['accounts']]
        edge_fields = [dict(name=n, type=t, role=r, non_null_values=self.edges,
                            type_valid_values=self.edges, null_values=0) for n,t,r in FIELD_SCHEMA['transfers']]
        return dict(schema_version='xgap-financial-graph-statistics-v1',
            measurement='actual emitted rows validated during this successful generation',
            nodes=self.nodes, edges=self.edges, directed=True,
            node_type_count=1 if self.nodes else 0, node_types={'Account': self.nodes},
            relation_type_count=1 if self.edges else 0,
            relation_types={'TRANSFERRED_TO': self.edges},
            fields={'accounts': node_fields, 'transfers': edge_fields},
            semantic_attributes=dict(node_schema_count=1, edge_schema_count=2, total_schema_count=3,
                node_value_count=self.nodes, edge_value_count=2*self.edges,
                total_value_count=self.nodes+2*self.edges,
                account_isBlocked=dict(type='boolean', true_count=self.blocked,
                    false_count=self.nodes-self.blocked, null_count=0),
                transfer_amount=dict(type='integer', unit='cents', non_null_count=self.edges,
                    min=self.amount_min, max=self.amount_max),
                transfer_timestamp=dict(type='integer', unit='UTC epoch milliseconds',
                    non_null_count=self.edges, min=self.timestamp_min, max=self.timestamp_max),
                note='Identifiers, type labels, endpoints, and bank ownership fields are not semantic attributes'),
            topology=dict(intra_bank_edges=self.intra_bank, inter_bank_edges=self.edges-self.intra_bank,
                intra_engine_edges=self.edges-self.cross_engine, cross_engine_edges=self.cross_engine,
                mean_out_degree=self.edges/self.nodes if self.nodes else None,
                mean_in_degree=self.edges/self.nodes if self.nodes else None,
                directed_density=self.edges/(self.nodes*(self.nodes-1)) if self.nodes > 1 else None,
                density_denominator='n*(n-1); directed graph without self-loops',
                simplicity='No self-loops checked per row; unique IDs and no duplicate ordered endpoint pair follow generator construction, not a global distinct-set measurement',
                cross_source_edges=[dict(source_count=s, cross_source_edges=c,
                    within_source_edges=self.edges-c) for s,c in zip(SOURCE_COUNTS,self.cross_source)]),
            shards=dict(actual_atomic_shards=sum(bool(n or e) for n,e in zip(self.node_banks,self.edge_banks)),
                banks=[dict(bank=b, intended_engine='neo4j' if b < 16 else 'rdf',
                    nodes=n, edges=e) for b,(n,e) in enumerate(zip(self.node_banks,self.edge_banks))],
                engine_assignment_edges=dict(neo4j=sum(self.edge_banks[:16]), rdf=sum(self.edge_banks[16:])),
                note='Canonical ownership shards only; no backend store has been materialized'),
            storage=dict(canonical_chunk_files=len(chunks),
                compressed_data_bytes=sum(c['bytes'] for c in chunks),
                filesystem_allocated_data_bytes=(sum(c['allocated_bytes'] for c in chunks)
                    if all(c['allocated_bytes'] is not None for c in chunks) else None),
                allocation_definition='Sum of canonical file stat.st_blocks times 512 where available; not unique physical storage, reservation, or quota usage',
                uncompressed_csv_bytes=sum(c['decoded_bytes'] for c in chunks),
                definition='CSV data including one header per chunk; metadata and backend stores excluded',
                backend_store_bytes=None, neo4j_relationships_materialized=None, rdf_triples_materialized=None))


def _report_rows(stats):
    attrs, topo, store = stats['semantic_attributes'], stats['topology'], stats['storage']
    rows = [
        ('nodes', stats['nodes'], 'logical nodes'), ('edges', stats['edges'], 'logical directed edges'),
        ('node_types', stats['node_type_count'], 'types'),
        ('relation_types', stats['relation_type_count'], 'relation types'),
        ('semantic_attribute_keys', attrs['total_schema_count'], 'schema keys'),
        ('node_attribute_values', attrs['node_value_count'], 'non-null values'),
        ('edge_attribute_values', attrs['edge_value_count'], 'non-null values'),
        ('total_attribute_values', attrs['total_value_count'], 'non-null values'),
        ('blocked_accounts', attrs['account_isBlocked']['true_count'], 'nodes'),
        ('atomic_shards', stats['shards']['actual_atomic_shards'], 'shards'),
        ('mean_out_degree', topo['mean_out_degree'], 'edges per node'),
        ('mean_in_degree', topo['mean_in_degree'], 'edges per node'),
        ('directed_density', topo['directed_density'], 'edges / n(n-1)'),
        ('intra_bank_edges', topo['intra_bank_edges'], 'edges'),
        ('inter_bank_edges', topo['inter_bank_edges'], 'edges'),
        ('intra_engine_edges', topo['intra_engine_edges'], 'edges'),
        ('cross_engine_edges', topo['cross_engine_edges'], 'edges'),
        ('compressed_data_bytes', store['compressed_data_bytes'], 'bytes'),
        ('uncompressed_csv_bytes', store['uncompressed_csv_bytes'], 'bytes'),
        ('filesystem_allocated_data_bytes', store['filesystem_allocated_data_bytes'], 'bytes; stat blocks'),
        ('canonical_chunk_files', store['canonical_chunk_files'], 'files')]
    rows += [(f'cross_source_edges_S{r["source_count"]}', r['cross_source_edges'], 'edges')
             for r in topo['cross_source_edges']]
    return rows


def _peak_rss_bytes(usage):
    return int(usage.ru_maxrss) * (1 if sys.platform == 'darwin' else 1024)

def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()


def _csv_bytes(row):
    buffer = io.StringIO(newline='')
    csv.writer(buffer, lineterminator='\n').writerow(row)
    return buffer.getvalue().encode('ascii')


class _DiskBudget:
    def __init__(self, root, maximum, reserve):
        self.root, self.maximum, self.reserve = root, maximum, reserve
        self.used = 0
        self.next_check = 0

    def write(self, handle, data):
        if self.used + len(data) > self.maximum:
            raise ValueError('Canonical output disk budget reached; partial files retained')
        if self.used >= self.next_check:
            if shutil.disk_usage(self.root).free < self.reserve + len(data):
                raise ValueError('Free disk reserve reached; partial files retained')
            self.next_check = self.used + 1024**2
        handle.write(data)
        self.used += len(data)

    def json(self, path, value):
        with path.open('xb') as handle:
            self.write(handle, _json_bytes(value))


class _CompressedSink:
    def __init__(self, handle, budget):
        self.handle, self.budget = handle, budget

    def write(self, data):
        self.budget.write(self.handle, data)
        return len(data)

    def flush(self):
        self.handle.flush()


def _pin(path, root):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024**2), b''):
            h.update(block)
    return dict(path=str(path.relative_to(root)), bytes=path.stat().st_size, sha256=h.hexdigest())


def generate(output, *, execute=False, nodes_per_bank=NODES_PER_BANK, seed=SEED,
             chunk_rows=100000, max_output_bytes=64*GIB, reserve_bytes=6*GIB):
    """Return a dry recipe by default; execute explicitly into a new directory.

    A failure retains partial chunks and intent; it never publishes success or
    resumes implicitly. No SQLite index or backend-specific copies are created.
    """
    started = time.perf_counter()
    usage_start = resource.getrusage(resource.RUSAGE_SELF)
    spec = recipe(nodes_per_bank=nodes_per_bank, seed=seed, chunk_rows=chunk_rows)
    if type(execute) is not bool:
        raise ValueError('Execute must be explicitly boolean')
    if (type(max_output_bytes) is not int or max_output_bytes < 1
            or type(reserve_bytes) is not int or reserve_bytes < 0):
        raise ValueError('Explicit nonnegative disk bounds required')
    root = Path(output).expanduser().resolve()
    planned = dict(executed=False, output=str(root), recipe=spec,
                   max_output_bytes=max_output_bytes, reserve_bytes=reserve_bytes)
    if not execute:
        return planned
    if root.exists():
        raise ValueError('Output already exists; do not overwrite or implicitly resume')
    if spec['output_bytes_upper_bound'] > max_output_bytes:
        raise ValueError('Declared output budget is below conservative canonical byte bound')
    parent = root.parent
    while not parent.exists():
        parent = parent.parent
    if shutil.disk_usage(parent).free < max_output_bytes + reserve_bytes:
        raise ValueError('Insufficient space for full declared output budget and reserve')
    root.mkdir(parents=True, exist_ok=False)
    budget = _DiskBudget(root, max_output_bytes, reserve_bytes)
    budget.json(root/'intent.json', planned)
    chunks = []
    digests = {}
    stats = _GraphStatistics()
    for kind, fields, maker in (('accounts', ACCOUNT_FIELDS, iter_accounts),
                                ('transfers', TRANSFER_FIELDS, iter_transfers)):
        overall = hashlib.sha256()
        overall.update(_csv_bytes(fields))
        for bank in range(BANKS):
            directory = root/f'bank-{bank:02d}'
            directory.mkdir(exist_ok=True)
            rows = iter(maker(bank, nodes_per_bank=nodes_per_bank, seed=seed))
            count = nodes_per_bank * (DEGREE if kind == 'transfers' else 1)
            for start in range(0, count, chunk_rows):
                path = directory/f'{kind}-{start//chunk_rows:06d}.csv.gz'
                partial = path.with_name(path.name+'.partial')
                h = hashlib.sha256()
                row_count = min(chunk_rows, count-start)
                decoded_bytes = 0
                with partial.open('xb') as raw:
                    with gzip.GzipFile(fileobj=_CompressedSink(raw, budget), filename='',
                                       mode='wb', mtime=0, compresslevel=1) as compressed:
                        header = _csv_bytes(fields)
                        compressed.write(header); h.update(header)
                        decoded_bytes += len(header)
                        for _ in range(row_count):
                            row = next(rows)
                            encoded = _csv_bytes(row)
                            compressed.write(encoded); h.update(encoded); overall.update(encoded)
                            stats.observe(kind, row)
                            decoded_bytes += len(encoded)
                partial.rename(path)
                chunks.append(dict(**_pin(path, root), kind=kind, owner_bank=bank,
                                   first_bank_row=start, rows=row_count,
                                   decoded_sha256=h.hexdigest(), decoded_bytes=decoded_bytes,
                                   allocated_bytes=(path.stat().st_blocks*512
                                       if hasattr(path.stat(), 'st_blocks') else None)))
            if next(rows, None) is not None:
                raise ValueError('Generator emitted more rows than its declared domain')
        digests[kind] = overall.hexdigest()
    fact_identity = dict(version=VERSION, seed=seed, nodes_per_bank=nodes_per_bank,
                         canonical_digests=digests)
    measured = stats.result(chunks)
    counts = dict(accounts=stats.nodes, logical_edges=stats.edges,
        intra_bank_edges=stats.intra_bank, inter_bank_edges=stats.edges-stats.intra_bank,
        out_degree=DEGREE)
    if counts != spec['counts']:
        raise ValueError('Observed generation counts differ from recipe; partial output retained')
    budget.json(root/'graph-statistics.json', measured)
    with (root/'graph-metrics.csv').open('xb') as handle:
        budget.write(handle, _csv_bytes(('metric', 'value', 'unit')))
        for row in _report_rows(measured):
            budget.write(handle, _csv_bytes(row))
    markdown = '# Generated canonical financial graph\n\nActual emitted and validated data; backend stores have not been materialized.\n\n| Metric | Value | Unit |\n| --- | ---: | --- |\n'
    markdown += ''.join(f'| {name} | {value} | {unit} |\n' for name,value,unit in _report_rows(measured))
    markdown += '\nSemantic attributes: Account.isBlocked; TRANSFERRED_TO.amount (integer cents), timestamp (UTC epoch milliseconds). IDs, type labels, endpoints, and bank fields are recorded separately in graph-statistics.json. Generation timing and process resource scope are in receipt.json.\n'
    with (root/'graph-metrics.md').open('xb') as handle:
        budget.write(handle, markdown.encode('utf-8'))
    manifest = dict(schema_version=VERSION, success=True, executed=True, recipe=spec,
        counts=counts, graph_statistics=measured, chunks=chunks, canonical_digests=digests,
        logical_facts_sha256=hashlib.sha256(_json_bytes(fact_identity)).hexdigest(),
        model_calls=0, backend_calls=0, query_calls=0, jobs_submitted=0,
        services_prepared=False, formal_workload_admitted=False)
    budget.json(root/'manifest.json', manifest)
    usage_end = resource.getrusage(resource.RUSAGE_SELF)
    receipt = dict(success=True, executed=True, counts=counts, chunks=len(chunks),
                   statistics=_pin(root/'graph-statistics.json', root),
                   metrics_csv=_pin(root/'graph-metrics.csv', root),
                   metrics_markdown=_pin(root/'graph-metrics.md', root),
                   generation_resources=dict(wall_seconds=time.perf_counter()-started,
                       cpu_user_seconds=usage_end.ru_utime-usage_start.ru_utime,
                       cpu_system_seconds=usage_end.ru_stime-usage_start.ru_stime,
                       process_peak_rss_bytes=_peak_rss_bytes(usage_end),
                       process_peak_rss_at_entry_bytes=_peak_rss_bytes(usage_start),
                       rss_scope='Current process lifetime high-water mark, not a phase-specific peak or child-process sum',
                       timing_scope='generate() entry through manifests/reports written; excludes final receipt serialization',
                       platform=sys.platform),
                   logical_facts_sha256=manifest['logical_facts_sha256'],
                   manifest=_pin(root/'manifest.json', root),
                   bytes_before_receipt=budget.used, max_output_bytes=max_output_bytes,
                   reserve_bytes=reserve_bytes, model_calls=0, backend_calls=0,
                   query_calls=0, jobs_submitted=0, services_prepared=False)
    # Include the final receipt itself in the artifact size without recursive
    # file hashing; JSON length reaches a fixed point after its decimal width.
    receipt['receipt_bytes'] = 0
    receipt['artifact_total_bytes'] = budget.used
    for _ in range(10):
        size = len(_json_bytes(receipt))
        if receipt['receipt_bytes'] == size:
            break
        receipt['receipt_bytes'] = size
        receipt['artifact_total_bytes'] = budget.used + size
    else:
        raise ValueError('Receipt byte-size accounting did not converge')
    budget.json(root/'receipt.json', receipt)
    return dict(receipt, output=str(root))
