#!/usr/bin/env python3
"""Official lookup example and unchanged ARUQULA search interface admission.

Environment/interface check only, zero model calls and no paper query outcomes.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from run_external_federation_tiny import Processes, ready
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.external_federation import deadline
from xgap.experiments.m15_native_services import LoopbackPortReservations
from xgap.experiments.one_shot_records import write_once

JAVA='/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home/bin/java'


def check(*, source, aruqula_source, aruqula_python, output, classpath=None):
    source=Path(source).resolve();aruqula_source=Path(aruqula_source).resolve()
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    processes=Processes(root);ports=None;started=time.perf_counter()
    receipt=dict(schema_version='xgap-ch7-official-lookup-admission-v1', success=False,
        model_calls=0, paper_result=False, baseline_source_changes=0,
        harness=file_pin(__file__),
        scope='official example RDF, indexer and lookup API; unchanged ARUQULA search_span only')
    try:
        with deadline(120):
            for name,path in [('lookup',source),('aruqula',aruqula_source)]:
                if subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=path,text=True):
                    raise ValueError(name+' tracked author source changed')
                receipt[name+'_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=path,text=True).strip()
            jar=source/'lookup/target/lookup-1.0-jar-with-dependencies.jar'
            launch=['-jar',str(jar)]
            if classpath is not None:
                # The author's assembly overwrites duplicate META-INF/services.
                # Separate unchanged dependency jars retain Java's normal SPI
                # discovery; no algorithm, POM or dependency version is changed.
                dependencies=Path(classpath).read_text().strip().split(':')
                if any(not Path(p).is_absolute() or not Path(p).is_file() for p in dependencies):
                    raise ValueError('Explicit original dependency jars required')
                jar=source/'lookup/target/lookup-1.0.jar'
                receipt['classpath']=file_pin(classpath)
                receipt['dependency_jars']=[file_pin(p) for p in dependencies]
                launch=['-cp',str(jar)+':'+':'.join(dependencies),'org.dbpedia.lookup.Main']
            receipt['jar']=file_pin(jar)
            # Use the author's installed YAML dependency, without changing the
            # separate XGAP measurement environment just to run this setup gate.
            yaml_code='import json,sys,yaml; print(json.dumps([yaml.safe_load(open(p)) for p in sys.argv[1:]]))'
            config,index=json.loads(subprocess.check_output([str(aruqula_python),'-c',yaml_code,
                str(source/'examples/config.yml'),str(source/'examples/indexing/ontology-file-indexer.yml')],
                text=True,timeout=10))
            config['indexPath']=str(root/'index')
            config_pin=write_once(root/'server-config.json',config)
            index['dataPath']=str(source/'examples/indexing/data')
            index_pin=write_once(root/'index-config.json',index)
            receipt.update(server_config=config_pin,index_config=index_pin,
                example_data=file_pin(source/'examples/indexing/data/openenergy-ontology.ttl'))
            ports=LoopbackPortReservations.acquire(1);port=ports.ports[0];ports.release(0)
            process=processes.start('lookup',[JAVA,'-Xms64m','-Xmx512m',*launch,
                '--config',config_pin['path'],'--port',str(port)],cwd=root)
            ready(process,port)
            base=f'http://127.0.0.1:{port}'
            boundary='xgap-official-index-config'
            body=(f'--{boundary}\r\nContent-Disposition: form-data; name="config"; filename="index.json"\r\n'
                'Content-Type: application/json\r\n\r\n').encode()+Path(index_pin['path']).read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
            request=Request(base+'/api/index/run',data=body,
                headers={'Content-Type':'multipart/form-data; boundary='+boundary},method='POST')
            with urlopen(request,timeout=60) as response:receipt['index_status']=response.status
            if receipt['index_status']!=200:raise RuntimeError('Official example indexing failed')
            endpoint=base+'/api/search'
            with urlopen(endpoint+'?'+urlencode(dict(query='fuel role',format='JSON',type='class',maxResults=5)),timeout=10) as response:
                docs=json.loads(response.read(2*1024**2))
            receipt['lookup_response']=write_once(root/'lookup-response.json',docs)
            wanted='http://openenergy-platform.org/ontology/oeo/OEO_00000001'
            receipt['expected_example_uri_present']=any(wanted in d.get('id',[]) for d in docs.get('docs',[]))
            code="import json,sys; from kg_utils import search_span; print(json.dumps(search_span(sys.argv[1], 'fuel role', return_full_results=True, type='class')))"
            client=processes.start('aruqula-lookup',[str(aruqula_python),'-c',code,endpoint],cwd=aruqula_source)
            client_code=client.wait(timeout=30)
            if client_code:raise RuntimeError('Original ARUQULA lookup call failed')
            result=json.loads((root/'aruqula-lookup.log').read_text().strip().splitlines()[-1])
            receipt['aruqula_expected_example_uri_present']=any(wanted in d.get('id',[]) for d in result)
            receipt['success']=receipt['expected_example_uri_present'] and receipt['aruqula_expected_example_uri_present']
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        receipt['processes']=processes.close()
        if ports:ports.close()
        receipt['all_owned_closed']=all(p['returncode'] is not None for p in receipt['processes'])
        receipt['success'] &= receipt['all_owned_closed']
        receipt['offline_elapsed_ms']=(time.perf_counter()-started)*1000
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps(dict(success=receipt['success'],receipt=pin,error=receipt.get('error'))))
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','aruqula-source','aruqula-python','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--classpath',help='Official POM dependency:build-classpath output; versions unchanged.')
    raise SystemExit(check(**vars(p.parse_args())))
