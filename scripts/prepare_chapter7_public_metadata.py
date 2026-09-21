#!/usr/bin/env python3
"""Publish RDF labels from the already-frozen public FinBench catalog.

Offline only. No questions, private intent, references, or result files are read.
This overlay is for both methods in a new matched RDF deployment; it never edits
an existing source snapshot or native experiment release.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import time

from xgap.catalog.bundle import FrozenResolutionBundle, read_file
from xgap.compilers.rdf_encoding import RdfEdgeEncoding
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.finbench_serving_profile import verify_asset
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once

RDF = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
RDFS = 'http://www.w3.org/2000/01/rdf-schema#'
OWL = 'http://www.w3.org/2002/07/owl#'


def iri(value):
    if not isinstance(value, str) or not value.startswith(('http://', 'https://')) or any(
            ord(c) <= 32 or c in '<>"{}|^`\\' for c in value):
        raise ValueError('Invalid public metadata IRI')
    return '<' + value + '>'


def label(value):
    escapes = {'\\': '\\\\', '"': '\\"', '\n': '\\n', '\r': '\\r', '\t': '\\t'}
    return '"' + ''.join(escapes.get(c, '\\u%04x' % ord(c) if ord(c) < 32 else c)
                         for c in value) + '"@en'


def words(value):
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', value).replace('_', ' ').strip()


def metadata_lines(catalog, bindings, mapping):
    """Pure conversion, shared public aliases unchanged, no query-aware ranking."""
    terms = mapping['backend_mapping']['term_mappings']['fuseki']
    encoding = RdfEdgeEncoding(**mapping['rdf_edge_encoding'])
    if encoding.label_encoding != 'mapped_iri' or encoding.class_predicate_iri != RDF + 'type':
        raise ValueError('Metadata requires the frozen mapped-IRI FinBench encoding')
    namespace = mapping['backend_mapping']['backends']['fuseki']['namespace']
    edge_kind = namespace + 'EdgeKind'
    emitted = set()

    def triple(subject, predicate, value):
        line = f'{iri(subject)} {iri(predicate)} {value} .\n'
        if line not in emitted:
            emitted.add(line)
            return [line]
        return []

    yield from triple(edge_kind, RDF + 'type', iri(OWL + 'Class'))
    yield from triple(edge_kind, RDFS + 'label', label('edge kind'))
    # Reification fields are actual predicates. Relation names are their values.
    for key, text in (('edge_class_iri', 'Edge'), ('source_predicate_iri', 'source'),
                      ('target_predicate_iri', 'target'), ('label_predicate_iri', 'edge label')):
        uri = getattr(encoding, key)
        yield from triple(uri, RDF + 'type', iri(OWL + 'Class' if key == 'edge_class_iri' else RDF + 'Property'))
        yield from triple(uri, RDFS + 'label', label(text))
    for name, term in sorted(terms.items()):
        kind, uri = term['kind'], term['representation']
        rdf_type = OWL + 'Class' if kind == 'class' else RDF + 'Property' if kind == 'property' else edge_kind
        if kind not in ('class', 'property', 'relation'):
            raise ValueError('Unknown mapped schema term')
        yield from triple(uri, RDF + 'type', iri(rdf_type))
        yield from triple(uri, RDFS + 'label', label(words(name)))
    for entry in catalog['entries']:
        binding = bindings[entry['candidate_id']]
        kind, value = binding['kind'], binding['value']
        if kind == 'entity':
            if binding.get('identity_property') != 'xgap_id':
                raise ValueError('Metadata requires the frozen canonical identity')
            uri = mapping['resource_namespace'] + value
        elif kind in ('type', 'predicate'):
            if value not in terms:
                raise ValueError('Catalog schema binding has no RDF representation')
            uri = terms[value]['representation']
        elif kind in ('source', 'scalar'):
            continue  # These scalar catalog entries are not new graph resources.
        else:
            raise ValueError('Unsupported public catalog kind')
        for text in (entry['canonical_label'], *entry.get('aliases', [])):
            if not isinstance(text, str) or not text.strip():
                raise ValueError('Invalid public catalog label')
            yield from triple(uri, RDFS + 'label', label(text))


def prepare(*, profile_path, profile_sha256, output):
    started = time.perf_counter()
    profile_path = Path(profile_path).resolve()
    doc = json.loads(read_pinned(profile_path, profile_sha256))
    catalog_root = (profile_path.parent / doc['catalog']['path']).resolve()
    FrozenResolutionBundle.load(catalog_root, expected_bundle_hash=doc['catalog']['bundle_hash'])
    catalog = json.loads(read_file(catalog_root / 'catalog.json'))
    bindings = json.loads(read_file(catalog_root / 'bindings.json'))
    materialization = Path(doc['offline']['materialization_root'])
    manifest = json.loads(read_pinned(materialization / 'manifest.json', doc['offline']['manifest_sha256']))
    verify_asset(materialization / 'mapping.json', manifest['output_files']['mapping.json'])
    mapping = json.loads((materialization / 'mapping.json').read_text())
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    inputs = dict(profile=dict(path=str(profile_path), sha256=profile_sha256),
        catalog_bundle_hash=doc['catalog']['bundle_hash'], mapping=file_pin(materialization / 'mapping.json'),
        catalog=file_pin(catalog_root / 'catalog.json'), bindings=file_pin(catalog_root / 'bindings.json'))
    write_once(root / 'input-seal.json', inputs)
    count = 0
    with (root / 'metadata.nt').open('x') as stream:
        for line in metadata_lines(catalog, bindings, mapping):
            stream.write(line)
            count += 1
    receipt = dict(schema_version='xgap-ch7-public-metadata-v1', success=True, inputs=inputs,
        dataset=doc['dataset'], metadata=file_pin(root / 'metadata.nt'), triples=count,
        public_catalog_entries=dict(Counter(e['kind'] for e in catalog['entries'])),
        output_semantics='public labels and schema declarations; source facts unchanged',
        shared_access_required=True, queries_read=0, answers_read=0, service_calls=0,
        benchmark_results=False, offline_elapsed_ms=(time.perf_counter()-started)*1000)
    pin = write_once(root / 'receipt.json', receipt)
    print(json.dumps(dict(success=True, receipt=pin, triples=count)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('profile-path', 'profile-sha256', 'output'):
        parser.add_argument('--' + name, required=True)
    prepare(**vars(parser.parse_args()))
