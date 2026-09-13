"""Shared, bounded HTTP observation and RDF result comparison for external engines.

This transport does not select sources, rewrite queries, or implement federation.
Payload accounting excludes headers, TCP/TLS and engine-internal work.
"""

from collections import Counter
from contextlib import contextmanager
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import signal
import threading
import time
from urllib.parse import parse_qs, urlsplit

from xgap.experiments.one_shot_records import write_once


MAX_BYTES = 16 << 20


def forwarding_headers(headers):
    # HTTP/2 upgrade belongs to the client/observer hop. In particular, Jena's
    # HTTP2-Settings field must not reach our HTTP/1.1 upstream connection.
    connection_fields = {x.strip().lower() for x in headers.get("Connection", "").split(",")}
    excluded = connection_fields | {"host", "connection", "content-length", "proxy-connection",
        "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade"}
    return {k:v for k,v in headers.items() if k.lower() not in excluded}


class DeadlineExceeded(TimeoutError):
    pass


@contextmanager
def deadline(seconds):
    """Main-thread wall deadline, preserving any shorter enclosing deadline."""
    if seconds <= 0:
        raise ValueError("Deadline must be positive")
    started = time.monotonic()
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_remaining, interval = signal.getitimer(signal.ITIMER_REAL)

    def expire(*_):
        raise DeadlineExceeded("Wall-clock budget exhausted; no retry")

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, min(seconds, previous_remaining) if previous_remaining else seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_remaining:
            signal.setitimer(signal.ITIMER_REAL, max(.000001, previous_remaining - (time.monotonic()-started)), interval)


def query_kind(text):
    # Classification only; native SPARQL parsers still perform all admission.
    match = re.match(r"\s*(?:(?:PREFIX\s+[^\s]*:\s*<[^>]*>|BASE\s*<[^>]*>)\s*)*(ASK|SELECT|CONSTRUCT|DESCRIBE)\b", text, re.I)
    return match.group(1).upper() if match else "OTHER"


def canonical_rows(document):
    """RDF term identity; preserve bags/order, reject unhandled blank-node scope.

    Plain literals and xsd:string are the same RDF 1.1 term. Numeric lexical forms
    are NOT coerced. A future numeric/blank-node benchmark needs its own contract.
    """
    variables = document["head"]["vars"]
    if len(set(variables)) != len(variables):
        raise ValueError("Repeated result variable")
    rows = []
    for row in document["results"]["bindings"]:
        if not set(row) <= set(variables):
            raise ValueError("Undeclared result variable")
        normalized = {}
        for name, term in row.items():
            kind, value = term["type"], term["value"]
            if not isinstance(value, str):
                raise ValueError("RDF lexical value must be text")
            if kind == "uri":
                normalized[name] = ["uri", value]
            elif kind in {"literal", "typed-literal"}:
                language = term.get("xml:lang", "").lower()
                datatype = term.get("datatype", "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString" if language else "http://www.w3.org/2001/XMLSchema#string")
                normalized[name] = ["literal", value, datatype, language]
            else:
                raise ValueError("Unsupported RDF result term: " + kind)
        rows.append(json.dumps(normalized, sort_keys=True, separators=(",", ":")))
    return sorted(variables), rows


def score_sparql(actual, expected, *, ordered):
    a_vars, a = canonical_rows(actual)
    e_vars, e = canonical_rows(expected)
    aa, ee = Counter(a), Counter(e)
    overlap = sum((aa & ee).values()) if a_vars == e_vars else 0
    return {"exact": a_vars == e_vars and (a == e if ordered else aa == ee),
            "bag_f1": (2 * overlap / (len(a)+len(e))) if a or e else float(a_vars == e_vars),
            "actual_rows": len(a), "expected_rows": len(e), "ordered": ordered}


def query_once(endpoint, query, *, seconds, output):
    """One read-only SELECT transport attempt; result bytes sealed before scoring."""
    u = urlsplit(endpoint)
    if u.scheme != "http" or u.hostname != "127.0.0.1":
        raise ValueError("Tiny gate permits explicit loopback HTTP endpoints only")
    record = {"status": "started", "endpoint": endpoint, "query":query,
              "query_sha256": hashlib.sha256(query.encode()).hexdigest(), "attempts": 1}
    write_once(Path(output).with_suffix(".intent.json"), record)
    started = time.perf_counter()
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=seconds)
    try:
        with deadline(seconds):
            conn.request("POST", u.path, query.encode(), {"Content-Type": "application/sparql-query", "Accept": "application/sparql-results+json"})
            response = conn.getresponse()
            record["http_status"] = response.status
            body = response.read(MAX_BYTES+1)
            if len(body) > MAX_BYTES:
                raise ValueError("Result byte budget exceeded")
            record.update(status="returned", body_utf8=body.decode("utf-8"), response_body_bytes=len(body))
    except Exception as error:
        record.update(status="failed", error_type=type(error).__name__, error=str(error))
    finally:
        conn.close()
        record["client_wall_ms"] = (time.perf_counter()-started)*1000
        write_once(output, record)
    return record


class SourceObserver:
    """Observe both methods at identical source boundaries; never retry or cache.

    A phase may change only after all observed requests finish. Injected failures
    are explicit fixtures, never requests sent to the underlying source.
    """
    def __init__(self, routes, root, *, max_calls=256, timeout_seconds=3,http_protocol_version='HTTP/1.0'):
        self.routes, self.root = dict(routes), Path(root)
        self.root.mkdir()
        self.max_calls, self.timeout = max_calls, timeout_seconds
        self.records, self.inflight = [], 0
        self.phase, self.fail_source = "initialization", None
        self.condition = threading.Condition()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                owner.forward(self)

            def do_POST(self):
                owner.forward(self)

        Handler.protocol_version=http_protocol_version
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = False
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .05})
        self.thread.start()

    @property
    def base_url(self):
        return "http://127.0.0.1:" + str(self.server.server_port)

    def set_phase(self, phase, *, fail_source=None):
        if not self.settle():
            raise RuntimeError("Cannot reassign active source calls to another query")
        with self.condition:
            self.phase, self.fail_source = phase, fail_source

    def settle(self):
        with self.condition:
            return self.condition.wait_for(lambda: self.inflight == 0, timeout=self.timeout+1)

    def forward(self, handler):
        started = time.perf_counter()
        source = urlsplit(handler.path).path
        with self.condition:
            index = len(self.records)
            record = {"index": index, "phase": self.phase, "source": source, "method": handler.command, "request_target": handler.path, "status": "started"}
            self.records.append(record)
            self.inflight += 1
            injected = source == self.fail_source
        conn = None
        try:
            handler.connection.settimeout(self.timeout)
            if index >= self.max_calls:
                raise ValueError("Source call budget exceeded")
            if handler.headers.get("Transfer-Encoding"):
                raise ValueError("Chunked request not supported by this bounded observer")
            length = int(handler.headers.get("Content-Length", "0"))
            if not 0 <= length <= MAX_BYTES:
                raise ValueError("Request byte budget exceeded")
            body = handler.rfile.read(length)
            if len(body) != length:
                raise ValueError("Truncated request")
            content_type = handler.headers.get("Content-Type", "")
            text = (body.decode() if content_type.startswith("application/sparql-query") else
                    parse_qs(body.decode() if handler.command == "POST" else urlsplit(handler.path).query).get("query", [""])[0])
            record.update(query=text, query_kind=query_kind(text), request_body_bytes=len(body), request_target_bytes=len(handler.path.encode()), injected=injected)
            write_once(self.root/f"{index:04}-intent.json", record)
            if injected:
                status, response_body, headers = 503, b"Injected tiny source unavailability", [("Content-Type", "text/plain")]
            else:
                upstream = urlsplit(self.routes[source])
                conn = http.client.HTTPConnection(upstream.hostname, upstream.port, timeout=self.timeout)
                target = upstream.path + (("?"+urlsplit(handler.path).query) if urlsplit(handler.path).query else "")
                request_headers = forwarding_headers(handler.headers)
                record["hop_headers_removed"] = sorted(k for k in handler.headers if k not in request_headers)
                conn.request(handler.command, target, body, request_headers)
                response = conn.getresponse()
                status, headers = response.status, response.getheaders()
                response_body = response.read(MAX_BYTES+1)
                if len(response_body) > MAX_BYTES:
                    raise ValueError("Source response byte budget exceeded")
            record.update(http_status=status, response_body_bytes=len(response_body), status="returned")
            response_path = self.root/f"{index:04}-response.bin"
            with response_path.open("xb") as saved:
                saved.write(response_body)
            record["response_sha256"] = hashlib.sha256(response_body).hexdigest()
            record["response_path"] = str(response_path)
            handler.send_response(status)
            for k,v in headers:
                if k.lower() in {"content-type", "content-encoding"}:
                    handler.send_header(k,v)
            handler.send_header("Content-Length", str(len(response_body)))
            handler.end_headers()
            handler.wfile.write(response_body)
        except Exception as error:
            record.update(status="failed", error_type=type(error).__name__, error=str(error))
            try:
                handler.send_error(502, "Source observer failure")
            except OSError:
                pass
        finally:
            if conn:
                conn.close()
            record["observer_wall_ms"] = (time.perf_counter()-started)*1000
            try:
                write_once(self.root/f"{index:04}-result.json", record)
            finally:
                with self.condition:
                    self.inflight -= 1
                    self.condition.notify_all()

    def snapshot(self, phase):
        if not self.settle():
            raise RuntimeError("Source accounting not settled")
        with self.condition:
            records = [dict(r) for r in self.records if r["phase"] == phase]
        return {"requests":len(records), "ask_requests":sum(r.get("query_kind")=="ASK" for r in records),
                "failed_requests":sum(r["status"]!="returned" or r.get("http_status", 599)>=400 for r in records),
                "request_body_bytes":sum(r.get("request_body_bytes",0) for r in records),
                "request_target_bytes":sum(r.get("request_target_bytes",0) for r in records),
                "response_body_bytes":sum(r.get("response_body_bytes",0) for r in records),
                "records":records}

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
