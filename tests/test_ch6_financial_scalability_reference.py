"""Reference answers require every frozen canonical byte/count to verify."""
from copy import deepcopy
import json

import pytest

from xgap.experiments.financial_runtime_inputs import checked_canonical_stream
from xgap.experiments.ch6_financial_scale import generate, iter_accounts, iter_transfers
from xgap.experiments.ch6_financial_scalability_queries import build_workload, reference_workload


@pytest.fixture
def canonical(tmp_path):
    root = tmp_path/'canonical'
    generate(root, execute=True, nodes_per_bank=9, chunk_rows=37,
        max_output_bytes=4*1024**2, reserve_bytes=0)
    return root, json.loads((root/'manifest.json').read_text())


@pytest.mark.parametrize('kind,maker', [('accounts', iter_accounts), ('transfers', iter_transfers)])
def test_verified_rows_match_frozen_generator_and_restore_canonical_order(canonical,kind,maker):
    root, manifest = canonical
    expected = [row for bank in range(32) for row in maker(bank,nodes_per_bank=9)]
    assert list(checked_canonical_stream(root,manifest,kind)) == expected
    shuffled = deepcopy(manifest); shuffled['chunks'].reverse()
    assert list(checked_canonical_stream(root,shuffled,kind)) == expected


def test_reference_completes_three_verified_passes_before_returning_answers(canonical):
    root, manifest = canonical; calls = []
    workload = build_workload(nodes_per_bank=9)
    def stream(kind):
        calls.append(kind)
        yield from checked_canonical_stream(root,manifest,kind)
    actual = reference_workload(workload,lambda:stream('accounts'),lambda:stream('transfers'))
    expected = reference_workload(workload,
        lambda:(row for bank in range(32) for row in iter_accounts(bank,nodes_per_bank=9)),
        lambda:(row for bank in range(32) for row in iter_transfers(bank,nodes_per_bank=9)))
    assert actual == expected and calls == ['transfers','accounts','transfers']


def test_changed_compressed_input_rejected_without_reference_result(canonical):
    root, manifest = canonical
    chunk = next(c for c in manifest['chunks'] if c['kind']=='transfers')
    path = root/chunk['path']; body = bytearray(path.read_bytes()); body[-1] ^= 1; path.write_bytes(body)
    with pytest.raises(ValueError,match='compressed chunk changed'):
        reference_workload(build_workload(nodes_per_bank=9),
            lambda:checked_canonical_stream(root,manifest,'accounts'),
            lambda:checked_canonical_stream(root,manifest,'transfers'))


@pytest.mark.parametrize('field,value', [('decoded_sha256','0'*64), ('decoded_bytes',1)])
def test_decoded_chunk_contract_mismatch_rejected(canonical,field,value):
    root, manifest = canonical
    chunk = next(c for c in manifest['chunks'] if c['kind']=='accounts'); chunk[field] = value
    with pytest.raises(ValueError,match='decoded chunk changed'):
        list(checked_canonical_stream(root,manifest,'accounts'))


@pytest.mark.parametrize('fault', ['global_digest','global_count','missing_chunk','duplicate_chunk','chunk_rows'])
def test_global_integrity_and_complete_chunk_coverage_required(canonical,fault):
    root, manifest = canonical
    if fault=='global_digest': manifest['canonical_digests']['transfers'] = '0'*64
    elif fault=='global_count': manifest['counts']['logical_edges'] += 1
    elif fault=='missing_chunk': manifest['chunks'].pop()
    elif fault=='duplicate_chunk': manifest['chunks'].append(deepcopy(manifest['chunks'][-1]))
    else: manifest['chunks'][-1]['rows'] -= 1
    with pytest.raises(ValueError,match='global count/digest|chunk|bank row count'):
        list(checked_canonical_stream(root,manifest,'transfers'))


def test_reference_stream_rejects_unknown_domain(canonical):
    root, manifest = canonical
    with pytest.raises(ValueError,match='kind must be'):
        list(checked_canonical_stream(root,manifest,'other'))
