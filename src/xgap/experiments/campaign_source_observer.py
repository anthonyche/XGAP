"""Per-phase bounded source observation; legacy tiny observer stays unchanged."""
from collections import Counter
from dataclasses import asdict, dataclass
import errno
import hashlib
import gzip
import http.client
import json
from pathlib import Path
import time
import threading
from urllib.parse import parse_qs, urlsplit

from xgap.experiments.external_federation import SourceObserver, forwarding_headers, query_kind
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.evidence_store import file_pin

MIB=1024**2


@dataclass(frozen=True)
class SourceObservationBudget:
    max_calls: int=65536
    request_bytes: int=16*MIB
    phase_request_bytes: int=128*MIB
    response_bytes: int=256*MIB
    phase_response_bytes: int=512*MIB
    timeout_seconds: int=120
    capture_compression: str='none'

    def __post_init__(self):
        if self.capture_compression not in ('none','gzip'):
            raise ValueError('Capture compression must be none or gzip')
        caps={'max_calls':1000000,'request_bytes':16*MIB,'phase_request_bytes':1024*MIB,
              'response_bytes':1024*MIB,'phase_response_bytes':4096*MIB,'timeout_seconds':120}
        for name,maximum in caps.items():
            value=getattr(self,name)
            if type(value) is not int or not 1<=value<=maximum:raise ValueError('Invalid observation budget: '+name)


class ObservationFailure(ValueError):
    def __init__(self,category,message):super().__init__(message);self.category=category


class CampaignSourceObserver(SourceObserver):
    def __init__(self,routes,root,*,budget:SourceObservationBudget,upstream_http_proxy=None,
                 downstream_keepalive=True):
        if not isinstance(budget,SourceObservationBudget):raise TypeError('An explicit source budget is required')
        if type(downstream_keepalive) is not bool:raise TypeError('Explicit boolean connection policy required')
        self.downstream_keepalive=downstream_keepalive
        # Explicit transport configuration, never inherited for local database
        # routes. This HTTP-only path preserves author request bytes and headers.
        self.upstream_http_proxy=urlsplit(upstream_http_proxy) if upstream_http_proxy else None
        if self.upstream_http_proxy:
            p=self.upstream_http_proxy
            if (p.scheme!='http' or not p.hostname or p.username or p.password or p.path not in ('','/')
                    or p.query or p.fragment or any(urlsplit(url).scheme!='http' for url in routes.values())):
                raise ValueError('An unauthenticated HTTP proxy and HTTP upstream routes are required')
        self.budget=budget;self.next_index=0;self.generation=0;self.accepting=True
        self.phase_request_bytes=0;self.phase_response_bytes=0;self.phase_calls=0
        self.sealed=None;self.released=True;self.late_calls=0;self.persistence_failures=0
        self.pool_lock=threading.Lock();self.idle_connections={};self.pool_closed=False;self.connection_sequence=0
        super().__init__(routes,root,max_calls=budget.max_calls,timeout_seconds=budget.timeout_seconds,http_protocol_version='HTTP/1.1')

    def take_connection(self,source,upstream):
        with self.pool_lock:
            pool=self.idle_connections.setdefault(source,[])
            while pool:
                conn,at,number=pool.pop()
                if time.monotonic()-at<=1:return conn,number,True
                conn.close()
            self.connection_sequence+=1
            destination=self.upstream_http_proxy or upstream
            return http.client.HTTPConnection(destination.hostname,destination.port,timeout=self.timeout),self.connection_sequence,False

    def return_connection(self,source,conn,number):
        with self.pool_lock:
            pool=self.idle_connections.setdefault(source,[])
            if self.pool_closed or len(pool)>=16:conn.close()
            else:pool.append((conn,time.monotonic(),number))

    def close(self):
        super().close()
        with self.pool_lock:
            self.pool_closed=True
            for pool in self.idle_connections.values():
                for conn,_,_ in pool:conn.close()
            self.idle_connections.clear()

    def set_phase(self,phase,*,fail_source=None):
        if not isinstance(phase,str) or not phase:raise ValueError('A phase identity is required')
        if fail_source is not None:raise ValueError('Campaign observer has no injected-failure mode')
        if not self.settle():raise RuntimeError('Cannot change a phase with active source requests')
        with self.condition:
            if self.inflight or self.late_calls or self.persistence_failures:
                raise RuntimeError('Source session requires recovery before reuse')
            if self.records or not self.released:raise RuntimeError('Seal the previous phase and its outcome before reuse')
            self.generation+=1;self.phase=phase;self.accepting=True;self.released=False;self.sealed=None
            self.phase_request_bytes=0;self.phase_response_bytes=0;self.phase_calls=0

    def forward(self,handler):
        started=time.perf_counter();source=urlsplit(handler.path).path
        with self.condition:
            index=self.next_index;self.next_index+=1;local_index=len(self.records)
            late=not self.accepting;self.late_calls+=int(late)
            record={'index':index,'phase':self.phase,'generation':self.generation,'source':source,
                'method':handler.command,'request_target':handler.path,'status':'started',
                'request_target_bytes':len(handler.path.encode()),'request_body_bytes':0,'response_body_bytes':0,
                'forwarded':False,'response_complete':False}
            self.records.append(record);self.inflight+=1;self.phase_calls+=1
            call_number=self.phase_calls
        compressed=self.budget.capture_compression=='gzip'
        conn=None;body_path=self.root/(f'{index:04}-response.bin'+('.gz' if compressed else ''));digest=hashlib.sha256()
        stage='incoming';headers_sent=False;reusable=False;connection_id=None
        try:
            handler.connection.settimeout(self.timeout)
            if late:raise ObservationFailure('harness_late_source_call','Source call arrived after phase sealing')
            if call_number>self.budget.max_calls:raise ObservationFailure('harness_call_budget','Per-phase source call budget exceeded')
            if source not in self.routes:raise ObservationFailure('harness_route','Unknown source route')
            if handler.headers.get('Transfer-Encoding'):raise ObservationFailure('harness_transport','Chunked request unsupported')
            length=int(handler.headers.get('Content-Length','0'))
            if not 0<=length<=self.budget.request_bytes:
                raise ObservationFailure('harness_request_budget','Per-request body limit exceeded')
            body=handler.rfile.read(length);record['request_body_bytes']=len(body)
            if len(body)!=length:raise ObservationFailure('harness_transport','Truncated incoming request')
            with self.condition:
                self.phase_request_bytes+=record['request_target_bytes']+len(body)
                over=self.phase_request_bytes>self.budget.phase_request_bytes
            if over:raise ObservationFailure('harness_request_budget','Per-phase incoming payload limit exceeded')
            content_type=handler.headers.get('Content-Type','')
            text=(body.decode() if content_type.startswith('application/sparql-query') else
                parse_qs(body.decode() if handler.command=='POST' else urlsplit(handler.path).query).get('query',[''])[0])
            record.update(query=text,query_kind=query_kind(text))
            if content_type.startswith('application/json'):
                # Observation only: forward the unchanged JSON bytes, including
                # native parameters. Never log authorization header values.
                try:
                    payload=json.loads(body)
                    if isinstance(payload,dict) and isinstance(payload.get('statements'),list):
                        record.update(query_language='cypher',native_statements=payload['statements'],
                                      request_body_sha256=hashlib.sha256(body).hexdigest())
                except (ValueError,TypeError):pass
            stage='persistence';write_once(self.root/f'{index:04}-intent.json',record)
            stage='upstream'
            upstream=urlsplit(self.routes[source]);conn,connection_id,reused=self.take_connection(source,upstream)
            record.update(upstream_connection_id=connection_id,upstream_connection_reused=reused)
            target=upstream.path+(('?'+urlsplit(handler.path).query) if urlsplit(handler.path).query else '')
            if self.upstream_http_proxy:target=upstream.scheme+'://'+upstream.netloc+target
            headers=forwarding_headers(handler.headers)
            record['hop_headers_removed']=sorted(k for k in handler.headers if k not in headers)
            record['forwarded']=True;conn.request(handler.command,target,body,headers)
            response=conn.getresponse();record['http_status']=response.status
            stage='persistence'
            with (gzip.open(body_path,'xb',compresslevel=1) if compressed else body_path.open('xb')) as saved:
                while True:
                    remaining=self.budget.response_bytes-record['response_body_bytes']
                    stage='upstream'
                    chunk=response.read(min(MIB,remaining+1))
                    if not chunk:
                        if response.length:raise http.client.IncompleteRead(b'',response.length)
                        break
                    record['response_body_bytes']+=len(chunk)
                    with self.condition:
                        self.phase_response_bytes+=len(chunk)
                        over=self.phase_response_bytes>self.budget.phase_response_bytes
                    stage='persistence';saved.write(chunk);digest.update(chunk)
                    if record['response_body_bytes']>self.budget.response_bytes or over:
                        raise ObservationFailure('harness_response_budget','Received source response byte limit exceeded')
            record.update(response_complete=True,status='returned')
            reusable=not response.will_close
            if response.status>=400:record['failure_category']='upstream_http_failure'
            stage='downstream';handler.send_response(response.status)
            if not self.downstream_keepalive:
                handler.send_header('Connection','close')
                handler.close_connection=True
            for k,v in response.getheaders():
                if k.lower() in {'content-type','content-encoding'}:handler.send_header(k,v)
            handler.send_header('Content-Length',str(record['response_body_bytes']));handler.end_headers();headers_sent=True
            stage='persistence'
            with (gzip.open(body_path,'rb') if compressed else body_path.open('rb')) as saved:
                while True:
                    stage='persistence';chunk=saved.read(MIB)
                    if not chunk:break
                    stage='downstream';handler.wfile.write(chunk)
        except Exception as error:
            category=(error.category if isinstance(error,ObservationFailure) else
                      'harness_persistence' if stage=='persistence' else
                      'harness_transport_resources' if stage=='upstream' and isinstance(error,OSError) and error.errno in
                          (errno.EADDRNOTAVAIL,errno.EMFILE,errno.ENFILE) else
                      'source_timeout' if stage=='upstream' and isinstance(error,TimeoutError) else
                      'source_transport' if stage=='upstream' else 'harness_transport')
            record.update(status='failed',error_type=type(error).__name__,error=str(error),failure_category=category)
            try:
                if not headers_sent:handler.send_error(502,'Source observation failed')
            except OSError:pass
        finally:
            if conn:
                if reusable:self.return_connection(source,conn,connection_id)
                else:conn.close()
            if body_path.exists():
                record.update(response_path=str(body_path),
                    response_sha256=None if record.get('failure_category')=='harness_persistence' else digest.hexdigest())
                if compressed:
                    try:
                        record.update(response_encoding='gzip',response_storage_pin=file_pin(body_path))
                    except OSError as error:
                        record.update(status='failed',failure_category='harness_persistence',
                                      error=str(error),response_sha256=None)
            record['observer_wall_ms']=(time.perf_counter()-started)*1000
            try:
                pin=write_once(self.root/f'{index:04}-result.json',record)
                compact={k:v for k,v in record.items() if k not in ('query','request_target','hop_headers_removed','native_statements')}
                compact['record_pin']=pin
                with self.condition:self.records[local_index]=compact
            except Exception:
                with self.condition:self.persistence_failures+=1
            finally:
                with self.condition:self.inflight-=1;self.condition.notify_all()

    def snapshot(self,phase):
        if not self.settle():raise RuntimeError('Source accounting not settled')
        with self.condition:
            if self.inflight:raise RuntimeError('Source accounting changed before snapshot')
            return self._snapshot_locked(phase)

    def _snapshot_locked(self,phase):
        if phase!=self.phase:raise ValueError('Read past phases through their immutable seals')
        rows=list(self.records)
        failures=Counter(r['failure_category'] for r in rows if r.get('failure_category'))
        return {'phase':phase,'generation':self.generation,'requests':len(rows),
            'ask_requests':sum(r.get('query_kind')=='ASK' for r in rows),
            'failed_requests':sum(r['status']!='returned' or r.get('http_status',599)>=400 for r in rows),
            'forwarded_requests':sum(r['forwarded'] for r in rows),'failure_categories':dict(failures),
            'upstream_connections_opened':sum(r.get('upstream_connection_reused') is False for r in rows),
            'upstream_connection_reuses':sum(r.get('upstream_connection_reused') is True for r in rows),
            'transport_profile':'HTTP/1.1;16idle connections/source;1s idle expiry;no automatic retries'+
                ('' if self.downstream_keepalive else ';downstream Connection: close'),
            'upstream_http_proxy':self.upstream_http_proxy.geturl() if self.upstream_http_proxy else None,
            'request_body_bytes':sum(r['request_body_bytes'] for r in rows),
            'request_target_bytes':sum(r['request_target_bytes'] for r in rows),
            'response_body_bytes':sum(r['response_body_bytes'] for r in rows),
            'capture_storage_bytes':sum(r.get('response_storage_pin',{}).get('bytes',r['response_body_bytes']) for r in rows),
            'capture_compression':self.budget.capture_compression,
            'partial_response_bytes':sum(r['response_body_bytes'] for r in rows if not r['response_complete']),
            'records_inline':False,'record_directory':str(self.root),'budget':asdict(self.budget),
            'first_index':rows[0]['index'] if rows else None,'last_index':rows[-1]['index'] if rows else None,
            'late_calls':self.late_calls,'persistence_failures':self.persistence_failures}

    def seal_phase(self,phase):
        if not self.settle():raise RuntimeError('Source accounting not settled')
        with self.condition:
            if self.inflight or self.persistence_failures or self.late_calls:raise RuntimeError('Cannot seal inconsistent source observations')
            if phase!=self.phase:raise ValueError('Cannot seal another phase')
            if self.sealed is not None:return dict(self.sealed)
            summary=self._snapshot_locked(phase)
            self.accepting=False
            index=[(r['index'],r['record_pin']['sha256']) for r in self.records]
            ledger=write_once(self.root/f'phase-{self.generation:04}-index.json',{
                'generation':self.generation,'phase':phase,'result_pattern':'{index:04}-result.json','files':index})
            summary['ledger_index']=ledger
            pin=write_once(self.root/f'phase-{self.generation:04}-summary.json',summary)
            self.sealed={**summary,'phase_seal':pin};return dict(self.sealed)

    def release_phase(self,phase,outcome_pin):
        outcome=json.loads(read_pinned(outcome_pin['path'],outcome_pin['sha256']))
        with self.condition:
            if self.inflight or self.late_calls or self.persistence_failures or phase!=self.phase or self.sealed is None:
                raise RuntimeError('A drained sealed phase is required')
            if outcome.get('source_observations',{}).get('phase_seal')!=self.sealed['phase_seal']:
                raise ValueError('Durable outcome does not reference this source phase seal')
            if self.released:raise ValueError('Phase already released')
            write_once(self.root/f'phase-{self.generation:04}-released.json',{'phase':phase,'generation':self.generation,
                'outcome':outcome_pin,'phase_seal':self.sealed['phase_seal'],'records_released':len(self.records)})
            self.records.clear();self.released=True
