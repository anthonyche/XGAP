"""Owned database handles; transport shutdown is never a termination receipt."""
from contextlib import contextmanager
from threading import Lock
import base64
import json
import re
import urllib.request
from xgap.backends.request_control import current_control
from xgap.backends.json_stream import read_json


def lifecycle(control,url,method,payload,headers,timeout):
    # Cleanup must remain possible after the request deadline is exhausted.
    with control.lock:control.lifecycle_calls+=1
    token=current_control.set(None)
    try:
        request=urllib.request.Request(url,data=None if payload is None else json.dumps(payload).encode(),headers=headers,method=method)
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=timeout) as response:
            body=response.read(65537)
            if len(body)>65536:raise ValueError('Database control response exceeds 64 KiB')
            parsed=json.loads(body)
            if not 200<=response.status<300:raise ValueError('Database control operation failed')
            return parsed
    finally:current_control.reset(token)


@contextmanager
def neo4j_transaction(client,control):
    base=f'{client.http_url}/db/{client.database}/tx'
    headers={'Accept':'application/json','Content-Type':'application/json',
        'Authorization':'Basic '+base64.b64encode(f'{client.user}:{client.password}'.encode()).decode()}
    timeout=min(5.,client.timeout_seconds)
    opened=lifecycle(control,base,'POST',{'statements':[]},headers,control.timeout(timeout))
    commit=opened.get('commit','')
    if opened.get('errors') or not re.fullmatch(re.escape(base)+r'/[0-9]+/commit',commit):
        raise ValueError('Neo4j did not return an owned same-origin transaction handle')
    url=commit[:-7];lock=Lock();done=False
    def rollback():
        nonlocal done
        with lock:
            if done:return {'backend':client.backend_id,'backend_termination_confirmed':True,'already_closed':True}
            result=lifecycle(control,url,'DELETE',None,headers,timeout)
            if result.get('errors') or 'errors' not in result:raise ValueError('Neo4j rollback not acknowledged')
            done=True
            return {'backend':client.backend_id,'transaction_id':url.rsplit('/',1)[-1],
                'backend_termination_confirmed':True,'operation':'rollback'}
    try:
        with control.cancellation(rollback):
            control.check()
            yield url
            control.check()
            with lock:
                if done:raise TimeoutError('Neo4j transaction cancelled')
                result=lifecycle(control,commit,'POST',{'statements':[]},headers,control.timeout(timeout))
                if result.get('errors') or 'errors' not in result:raise ValueError('Neo4j commit not acknowledged')
                done=True
    finally:
        if not done:control._invoke(rollback)


@contextmanager
def fuseki_query(client,control):
    base=f'{client.base_url}/{client.dataset}'
    headers={'Content-Type':'application/json','Accept':'application/json'}
    timeout=min(5.,client.timeout_seconds)
    registered=lifecycle(control,base+'/xgap-control','POST',{'action':'register'},headers,control.timeout(timeout))
    handle=registered.get('handle','')
    if not re.fullmatch(r'[a-f0-9]{64}',handle):raise ValueError('Fuseki cancellation registration returned invalid handle')
    done=False;lock=Lock()
    def cancel():
        nonlocal done
        with lock:
            if done:return {'backend':client.backend_id,'backend_termination_confirmed':True,'already_closed':True}
            response=lifecycle(control,base+'/xgap-control','POST',{'action':'cancel','handle':handle},headers,timeout)
            confirmed=response.get('backend_termination_confirmed') is True and response.get('handle')==handle
            if not confirmed:raise ValueError('Fuseki query termination was not confirmed')
            done=True
            return {'backend':client.backend_id,'backend_termination_confirmed':True,'operation':'abort_and_end'}
    try:
        with control.cancellation(cancel):
            control.check();yield base+'/xgap-query',{'X-XGAP-Handle':handle};control.check()
    finally:
        # Even a fully read HTTP body need not imply the server finally-block ended.
        if not done:control._invoke(cancel)
