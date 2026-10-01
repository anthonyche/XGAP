"""Provider usage is measured; streaming without usage is never guessed."""
import gzip
import json
from types import SimpleNamespace

from check_chapter7_aruqula_fedup import observed_model_usage


def record(tmp_path, index, body):
    path = tmp_path / f'{index}.gz'
    path.write_bytes(gzip.compress(body))
    return dict(index=index, forwarded=True, response_complete=True, http_status=200,
                response_path=str(path), response_encoding='gzip')


def test_stream_uses_last_cumulative_usage_without_summing_it_twice(tmp_path):
    events = [dict(usage={'prompt_tokens':10,'completion_tokens':2}),
              dict(usage={'prompt_tokens':10,'completion_tokens':5})]
    body = ''.join('data: '+json.dumps(e)+'\n\n' for e in events).encode()+b'data: [DONE]\n\n'
    result = observed_model_usage(SimpleNamespace(records=[record(tmp_path,0,body)]))
    assert result['usage_complete']
    assert (result['model_network_calls'],result['input_tokens'],result['output_tokens']) == (1,10,5)


def test_one_missing_provider_usage_keeps_batch_tokens_unknown(tmp_path):
    known = json.dumps(dict(usage={'prompt_tokens':10,'completion_tokens':5})).encode()
    missing = b'data: {"choices":[]}\n\ndata: [DONE]\n\n'
    result = observed_model_usage(SimpleNamespace(records=[record(tmp_path,0,known),record(tmp_path,1,missing)]))
    assert result['model_network_calls'] == 2 and not result['usage_complete']
    assert result['input_tokens'] is None and result['output_tokens'] is None
    assert result['records'][0]['usage'] == dict(input_tokens=10,output_tokens=5)
