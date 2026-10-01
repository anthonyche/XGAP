"""Only the new comparator boundary: RDF identity, multiplicity and wall cutoff."""
import json
from pathlib import Path
import time

import pytest

from xgap.experiments.external_federation import DeadlineExceeded, canonical_rows, deadline, score_sparql


FIXTURE=Path(__file__).parent/"fixtures/external_federation"


def test_bag_and_order_are_not_silently_discarded():
    gold=json.loads((FIXTURE/"gold.json").read_text())
    expected=gold["duplicate_bag"]
    deduplicated=json.loads(json.dumps(expected))
    deduplicated["results"]["bindings"].pop()
    score=score_sparql(deduplicated,expected,ordered=False)
    assert not score["exact"] and score["bag_f1"]==pytest.approx(2/3)
    expected=gold["cross_ordered"]
    reversed_rows=json.loads(json.dumps(expected))
    reversed_rows["results"]["bindings"].reverse()
    assert not score_sparql(reversed_rows,expected,ordered=True)["exact"]
    assert score_sparql(reversed_rows,expected,ordered=False)["exact"]


def test_rdf_identity_normalizes_strings_but_not_uris_or_numeric_lexical_forms():
    make=lambda term:{"head":{"vars":["x"]},"results":{"bindings":[{"x":term}]}}
    plain=make({"type":"literal","value":"1"})
    typed=make({"type":"literal","value":"1","datatype":"http://www.w3.org/2001/XMLSchema#string"})
    assert score_sparql(plain,typed,ordered=False)["exact"]
    assert not score_sparql(plain,make({"type":"uri","value":"1"}),ordered=False)["exact"]
    n=lambda x:make({"type":"literal","value":x,"datatype":"http://www.w3.org/2001/XMLSchema#integer"})
    assert not score_sparql(n("01"),n("1"),ordered=False)["exact"]
    with pytest.raises(ValueError,match="Unsupported RDF"):
        canonical_rows(make({"type":"bnode","value":"a"}))
    with pytest.raises(KeyError):
        canonical_rows({"error":"timeout"})


def test_nested_deadline_cannot_extend_outer_wall_budget():
    started=time.monotonic()
    with pytest.raises(DeadlineExceeded):
        with deadline(.08):
            with deadline(3):
                time.sleep(1)
    assert time.monotonic()-started < .6
    # The alarm is restored, so no delayed signal leaks into the next request.
    import signal
    assert signal.getitimer(signal.ITIMER_REAL)==(0.0,0.0)


def test_observer_does_not_forward_client_http2_upgrade_to_http1_source(tmp_path):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import http.client
    import threading
    from xgap.experiments.external_federation import SourceObserver
    captured=[]
    class Source(BaseHTTPRequestHandler):
        def log_message(self,*_): pass
        def do_GET(self):
            captured.append(dict(self.headers))
            self.send_response(200); self.send_header("Content-Length","4"); self.end_headers();self.wfile.write(b"true")
    server=HTTPServer(("127.0.0.1",0),Source)
    thread=threading.Thread(target=server.serve_forever,kwargs={"poll_interval":.01});thread.start()
    observer=SourceObserver({"/a":f"http://127.0.0.1:{server.server_port}/query"},tmp_path/"observer")
    try:
        client=http.client.HTTPConnection("127.0.0.1",observer.server.server_port)
        client.request("GET","/a?query=ASK%20%7B%7D",headers={"Connection":"Upgrade, HTTP2-Settings", "Upgrade":"h2c","HTTP2-Settings":"example","Accept":"application/sparql-results+json"})
        response=client.getresponse(); assert response.status==200 and response.read()==b"true";client.close()
        assert not {"connection","upgrade","http2-settings"}&{k.lower() for k in captured[0]}
        assert captured[0]["Accept"]=="application/sparql-results+json"
        observed=observer.snapshot("initialization")
        assert observed["ask_requests"]==1 and observed["failed_requests"]==0
    finally:
        observer.close();server.shutdown();server.server_close();thread.join()
