#!/usr/bin/env python3
"""One owned tiny admission of the original ARUQULA API plus actual FedUP.

Not a formal comparison. Every original exploration/model call is observed;
wrong answers and failures remain evidence. No repeat of an attempted output.
"""
import argparse
import getpass
import gzip
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.request import Request, getproxies, proxy_bypass, urlopen

from check_common_rdf_trial import JAVA, FUSEKI, JARS, PINS
from prepare_chapter7_public_metadata import prepare as prepare_metadata
from run_bounded_joint_batch import BatchBudget, source_commit
from run_external_federation_tiny import Processes, ready
from xgap.experiments.campaign_source_observer import CampaignSourceObserver, SourceObservationBudget
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.external_federation import deadline
from xgap.experiments.financial_nl_profile import INPUT_ROOT
from xgap.experiments.finbench_serving_profile import verify_asset
from xgap.experiments.m15_native_services import LoopbackPortReservations, _fuseki_server_configuration
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.owned_resources import OwnedProcess, OwnedResources
from xgap.experiments.process_guard import ProcessBudget, run_guarded_command, _group_sample

REPO = Path(__file__).resolve().parents[1]
DATA = Path('/Users/anthonyche/xgap-data')
AUTHOR = DATA / 'aruqula-intake-20260920-v1'
PYTHON = DATA / 'aruqula-runtime-20260921-v1/venv/bin/python'
LOOKUP = DATA / 'ch7-lookup-intake-20260921-v1/source'
CLASSPATH = DATA / 'ch7-lookup-intake-20260921-v1/runtime-classpath.txt'
REDIS = DATA / 'ch7-baseline-dependencies-20260921-v1/redis-github/source/src/redis-server'
QUESTION = ('For person with business ID 1, find accounts owned by that person that sent money '
    'to blocked accounts owned by a company. Include transfers whose createTime is between '
    '2020-01-01 00:00:00.000 and 2020-01-04 00:00:00.000, inclusive. '
    'For each company and receiving account, return company_id, account_id and total_amount '
    '(sum of transferred amount, rounded to three decimal places). '
    'Order by company_id then account_id ascending, without a result limit.')


def admission_case(name):
    """Prespecified source strata, independent of observed method outcomes."""
    if name == 'cross-source':
        return dict(question_id='CH7-ARUQULA-TINY-01', question=QUESTION,
                    sources=('graph', 'control'), workload_stratum='cross_source_unambiguous')
    if name == 'single-source':
        return dict(question_id='CH6-ARUQULA-SINGLE-01',
            question=('List the business IDs of all accounts as account_id, '
                      'ordered by account_id ascending, without a result limit.'),
            sources=('graph',), workload_stratum='W1_single_source_unambiguous')
    raise ValueError('Unknown admission case')


def reference_for_case(name):
    """Evaluator-only values: invoke after the author outcome is sealed."""
    if name == 'single-source':
        return ([dict(account_id=str(i)) for i in (1, 2, 3, 4)],
                dict(schema_version='xgap-row-normalization-v1', fields={'account_id': 'text'}))
    if name != 'cross-source':
        raise ValueError('Unknown admission case')
    import sys
    sys.path.insert(0, str(REPO/'tests'))
    from test_finbench_rdf import expected_rows
    from xgap.experiments.finbench_one_shot_population import normalization
    from xgap.experiments.finbench_rdf import FAMILIES
    return expected_rows()[0], normalization(FAMILIES[0])


def observed_model_usage(observer):
    """A response without provider usage stays unknown, including streaming."""
    totals = dict(input_tokens=0, output_tokens=0)
    records = []
    for record in observer.records:
        usage = None
        if record.get('response_complete') and record.get('http_status') == 200:
            try:
                path = Path(record['response_path'])
                body = gzip.decompress(path.read_bytes()) if record.get('response_encoding') == 'gzip' else path.read_bytes()
                try:
                    payloads = [json.loads(body)]
                except (ValueError, UnicodeError):
                    payloads = [json.loads(line[5:].strip()) for line in body.decode().splitlines()
                                if line.startswith('data:') and line[5:].strip() not in ('', '[DONE]')]
                values = [p.get('usage') for p in payloads if isinstance(p, dict) and isinstance(p.get('usage'), dict)]
                if values:
                    last = values[-1]
                    a, b = last.get('prompt_tokens'), last.get('completion_tokens')
                    if type(a) is int and type(b) is int and a >= 0 and b >= 0:
                        usage = dict(input_tokens=a, output_tokens=b)
            except (OSError, ValueError, UnicodeError):
                pass
        records.append(dict(index=record['index'], usage=usage))
        if usage:
            for key in totals:
                totals[key] += usage[key]
    known = all(r['usage'] is not None for r in records)
    return dict(model_network_calls=sum(r['forwarded'] for r in observer.records),
        usage_complete=known, **{k: v if known else None for k, v in totals.items()}, records=records)


def public_source_loads(profile, metadata, output):
    """Honor the declared representation; never fall back to old raw copies."""
    from rdflib import Graph
    loads=profile['offline']['rdf_loads']
    original={name:read_pinned(loads[name]['path'],loads[name]['sha256']) for name in ('graph','control')}
    graph=Graph().parse(data=original['graph'].decode(),format='turtle')
    control=Graph().parse(data=original['control'].decode(),format='turtle')
    graph.parse(metadata,format='nt')
    if graph&control:raise ValueError('Declared disjoint public source facts overlap')
    target=Path(output)/'graph.ttl'
    target.write_bytes(original['graph']+b'\n'+Path(metadata).read_bytes())
    return target,Path(loads['control']['path'])


def check(*, profile_path, profile_sha256, output, read_key=False, federation='fedup', fedx_build=None,
          case='cross-source', compatibility='original'):
    selected = admission_case(case)
    if federation=='single-fuseki' and selected['sources']!=('graph',):
        raise ValueError('Native single-endpoint admission cannot be labeled cross-source')
    commit = source_commit()
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    processes = Processes(root)
    observers, ports = {}, None
    owned = []
    prior_key = os.environ.get('XGAP_EXTERNAL_LLM_API_KEY')
    receipt = dict(schema_version='xgap-ch6-external-composition-admission-v2', source_commit=commit,
        composition='aruqula-'+federation,
        success=False, composition_admitted=False, paper_result=False, attempts=1,
        automatic_retries=0, baseline_algorithm_changes=0, original_prompt_changes=0)
    receipt.update(admission_case=case, workload_stratum=selected['workload_stratum'],
                   execution_sources=list(selected['sources']), compatibility=compatibility)
    # Three fixed Jena TDB stores alone occupy about 576 MiB before any trial.
    design = dict(total_wall_seconds=900, package_max_bytes=1024**3, free_disk_reserve_bytes=6*1024**3)
    study = BatchBudget(root, design, time.time())
    try:
        with deadline(900):
            # Match the existing compact client's OS-configured network path;
            # local source/lookup observers remain direct. Do not change author
            # prompts, decoding, request bodies or retry behavior.
            model_proxy = None if proxy_bypass('112.95.75.67') else getproxies().get('http')
            if study.sample([]):
                raise ValueError(study.status)
            profile = json.loads(read_pinned(profile_path, profile_sha256))
            materialization = Path(profile['offline']['materialization_root'])
            manifest = json.loads(read_pinned(materialization/'manifest.json', profile['offline']['manifest_sha256']))
            if materialization != INPUT_ROOT or (manifest['entity_count'], manifest['relationship_count']) != (8, 16):
                raise ValueError('Admission requires the existing eight-entity development snapshot')
            for name in ('graph.ttl', 'control.ttl'):
                verify_asset(materialization/name,manifest['output_files'][name])
            if federation not in ('fedup','fedx','single-fuseki'):raise ValueError('Unknown original endpoint configuration')
            fedx=None
            if federation=='fedx':
                build=json.loads(Path(fedx_build).read_text())
                if not build['external_entries_byte_identical']:raise ValueError('Changed external FedX code')
                fedx=build['jar']
                read_pinned(build['source']['path'],build['source']['sha256'])
                if file_pin(fedx['path'])!=fedx:raise ValueError('FedX transport build changed')
                receipt['transport_build']=file_pin(fedx_build)
            for name in (('fedup', 'summary') if federation=='fedup' else ()):
                if file_pin(JARS[name])['sha256'] != PINS[name]:
                    raise ValueError('Original author JAR changed')
            if file_pin(REDIS)['sha256'] != 'fd2e0635cfad3a62e87a638d2d9948f967ae886715f6177c07f812046a894acb':
                raise ValueError('Admitted Redis binary changed')
            for repository, expected in ((AUTHOR, '9a3982baca03d62f7250572e300b1e4ba47727cc'),
                                         (LOOKUP, '939b3f36fefafca444cc6dff6c568c5b559f58e0')):
                head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repository, text=True).strip()
                if head != expected or subprocess.check_output(['git', 'diff', 'HEAD', '--'], cwd=repository):
                    raise ValueError('Pinned author tracked files changed')
            request = write_once(root/'request.json', {k:selected[k] for k in ('question_id','question')})
            receipt['input_seal'] = write_once(root/'input-seal.json', dict(profile=dict(path=profile_path,
                sha256=profile_sha256), request=request, budget=design, public_question_exposure='old tiny development',
                worker_budget=dict(wall_seconds=300, max_group_rss_bytes=2*1024**3),
                admission_case=case, execution_sources=list(selected['sources']),
                compatibility=compatibility,
                workload_stratum=selected['workload_stratum'],
                maximum_model_calls=64, maximum_source_calls=256, official_lookup_config=file_pin(LOOKUP/'examples/config.yml'),
                model_transport='explicit system HTTP proxy' if model_proxy else 'direct HTTP',
                composition='aruqula-'+federation,
                jars=({name:file_pin(JARS[name]) for name in ('fedup','summary')} if federation=='fedup'
                      else dict(fedx=fedx) if federation=='fedx' else {}), redis=file_pin(REDIS),
                worker=file_pin(REPO/'scripts/run_chapter7_aruqula_worker.py'), classpath=file_pin(CLASSPATH),
                lookup_jar=file_pin(LOOKUP/'lookup/target/lookup-1.0.jar')))
            prepare_metadata(profile_path=profile_path, profile_sha256=profile_sha256, output=root/'public-metadata')
            graph,control=public_source_loads(profile,root/'public-metadata/metadata.nt',root)
            source_loads=[(name,dict(graph=graph,control=control)[name]) for name in selected['sources']]
            receipt['public_sources'] = {name:file_pin(path) for name,path in source_loads}
            # Redis's fixed localhost port is an original interface requirement.
            # Own a fresh empty instance; never clear or commandeer another one.
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 6379))
            redis = processes.start('redis', [str(REDIS),'--bind','127.0.0.1','--port','6379',
                '--save','','--appendonly','no','--dir',str(root)])
            ready(redis,6379)
            owned.append(OwnedProcess('redis','method_host',redis))
            ports = LoopbackPortReservations.acquire(4)
            routes = {}
            for index,(name,load) in enumerate(source_loads):
                state = root/('fuseki-'+name)
                state.mkdir()
                (state/'config.ttl').write_text(_fuseki_server_configuration(query_timeout_seconds=20))
                port = ports.ports[index]
                ports.release(index)
                process = processes.start('source-'+name,[str(FUSEKI/'fuseki-server'),'--localhost','--port',str(port),
                    '--file',str(load),'/'+name],cwd=FUSEKI,
                    env={'JAVA':JAVA,'FUSEKI_HOME':str(FUSEKI),'FUSEKI_BASE':str(state),'JVM_ARGS':'-Xms64m -Xmx512m'})
                ready(process,port)
                owned.append(OwnedProcess(name,'source',process))
                routes['/'+name+'/sparql'] = f'http://127.0.0.1:{port}/{name}/sparql'
            source_budget = SourceObservationBudget(max_calls=256,response_bytes=8*1024**2,
                phase_response_bytes=64*1024**2,timeout_seconds=20,capture_compression='gzip')
            observers['source'] = CampaignSourceObserver(routes,root/'source-observations',budget=source_budget)
            endpoints = [observers['source'].base_url+'/'+name+'/sparql' for name,_ in source_loads]
            prefixes, graphs = set(), []
            for (_,load),endpoint in zip(source_loads, endpoints):
                body = []
                for line in load.read_text().splitlines():
                    if line.startswith('@prefix '): prefixes.add(line)
                    else: body.append(line)
                graphs.append('<'+endpoint+'> {\n'+'\n'.join(body)+'\n}')
            trig = root/'summary-input.trig'
            trig.write_text('\n'.join(sorted(prefixes))+'\n'+'\n'.join(graphs))
            summary = root/'summary'
            summary.mkdir()
            if federation=='fedup':
                processes.command('summary-load',[JAVA,'-Xmx512m','-cp',str(JARS['fedup']),'tdb2.tdbloader',
                    '--loc',str(root/'summary-input'),str(trig)],seconds=40)
                processes.command('summary-build',[JAVA,'-Xmx512m','-jar',str(JARS['summary']),
                    '--input',str(root/'summary-input'),'--output',str(summary),'--hash','1'],seconds=40)
                receipt['offline_summary'] = write_once(root/'summary-seal.json',dict(
                    files=[file_pin(p) for p in sorted(summary.rglob('*')) if p.is_file()], hash_modulo=1))
                shutil.copytree(summary,root/'serving-summary')
            if federation=='single-fuseki':
                endpoint=endpoints[0]
                receipt['endpoint_role']='native_single_source; no federation engine'
            else:
                port = ports.ports[2]
                ports.release(2)
                command=([JAVA,'-Xms64m','-Xmx512m','-jar',str(JARS['fedup']),
                    '--port',str(port),'--summaries',str(root/'serving-summary'),'--engine','FedX','--modify','(e) -> e']
                    if federation=='fedup' else [JAVA,'-Xms64m','-Xmx512m','-jar',fedx['path'],str(port),'20',*endpoints])
                host = processes.start(federation,command)
                ready(host,port)
                owned.append(OwnedProcess(federation,'method_host',host))
                endpoint=f'http://127.0.0.1:{port}/'+('serving-summary/sparql' if federation=='fedup' else 'sparql')
            observers['federation'] = CampaignSourceObserver({'/sparql':endpoint},
                root/'federation-observations',budget=source_budget)
            yaml_code = 'import json,sys,yaml; print(json.dumps([yaml.safe_load(open(p)) for p in sys.argv[1:]]))'
            config,index = json.loads(subprocess.check_output([str(PYTHON),'-c',yaml_code,
                str(LOOKUP/'examples/config.yml'),str(LOOKUP/'examples/indexing/ontology-file-indexer.yml')],text=True,timeout=10))
            config['indexPath'] = str(root/'lookup-index')
            config_pin = write_once(root/'lookup-config.json',config)
            index['dataPath'] = str(root/'public-metadata')
            index_pin = write_once(root/'lookup-index-config.json',index)
            port = ports.ports[3]
            ports.release(3)
            lookup = processes.start('lookup',[JAVA,'-Xms64m','-Xmx512m','-cp',
                str(LOOKUP/'lookup/target/lookup-1.0.jar')+':'+CLASSPATH.read_text().strip(),
                'org.dbpedia.lookup.Main','--config',config_pin['path'],'--port',str(port)],cwd=root)
            ready(lookup,port)
            owned.append(OwnedProcess('lookup','method_host',lookup))
            boundary = 'xgap-official-index-config'
            body = (f'--{boundary}\r\nContent-Disposition: form-data; name="config"; filename="index.json"\r\n'
                'Content-Type: application/json\r\n\r\n').encode()+Path(index_pin['path']).read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
            with urlopen(Request(f'http://127.0.0.1:{port}/api/index/run',data=body,
                headers={'Content-Type':'multipart/form-data; boundary='+boundary}),timeout=60) as response:
                if response.status != 200: raise ValueError('Official lookup indexing failed')
            observers['lookup'] = CampaignSourceObserver({'/api/search':f'http://127.0.0.1:{port}/api/search'},
                root/'lookup-observations',budget=source_budget)
            observers['model'] = CampaignSourceObserver({'/v1/chat/completions':'http://112.95.75.67:9018/v1/chat/completions'},
                root/'model-observations',budget=SourceObservationBudget(max_calls=64,response_bytes=8*1024**2,
                    phase_response_bytes=64*1024**2,timeout_seconds=70,capture_compression='gzip'),
                upstream_http_proxy=model_proxy)
            for observer in observers.values(): observer.set_phase('aruqula')
            if read_key:
                os.environ['XGAP_EXTERNAL_LLM_API_KEY'] = getpass.getpass('Qwen credential (not recorded): ')
            if not os.environ.get('XGAP_EXTERNAL_LLM_API_KEY'):
                raise ValueError('Model credential unavailable')
            resources = OwnedResources(owned,method_rss_bytes=3*1024**3,source_rss_bytes=2*1024**3,extra_monitor=study)
            command = [str(PYTHON),str(REPO/'scripts/run_chapter7_aruqula_worker.py'),
                '--method-id','aruqula-'+federation,
                '--compatibility',compatibility,
                '--author-source',str(AUTHOR),'--request-path',request['path'],'--request-sha256',request['sha256'],
                '--model-endpoint',observers['model'].base_url+'/v1','--model-id','qwen3.8-27b',
                '--federation-endpoint',observers['federation'].base_url+'/sparql',
                '--lookup-endpoint',observers['lookup'].base_url+'/api/search','--output',str(root/'worker')]
            receipt['guard'] = run_guarded_command(command,cwd=REPO,output=root/'guard',
                budget=ProcessBudget(wall_seconds=300,max_group_rss_bytes=2*1024**3,max_log_bytes=8*1024**2),
                resource_monitor=resources)
            receipt['resources'] = resources.summary()
            receipt['observations'] = {name:observer.seal_phase('aruqula') for name,observer in observers.items()}
            receipt['model_usage'] = observed_model_usage(observers['model'])
            if (root/'worker/receipt.json').exists():
                receipt['worker'] = file_pin(root/'worker/receipt.json')
                outcome = json.loads((root/'worker/receipt.json').read_text())
                receipt['composition_admitted'] = (receipt['guard']['success'] and outcome['success'] and
                    receipt['model_usage']['model_network_calls'] > 0 and
                    receipt['observations']['source']['forwarded_requests'] > 0)
                # Only now open the independent, previously hand-derived tiny
                # answer. The method never receives this query or these rows.
                answer = json.loads(read_pinned(outcome['answer']['path'],outcome['answer']['sha256'])) if outcome['success'] else None
                result = write_once(root/'result.json',dict(answer_format='sparql_json',answer=answer))
                common = dict(schema_version='xgap-common-method-trial-v1',method='aruqula-'+federation,track='natural_language',
                    question_id=selected['question_id'],dataset=profile['dataset'],population='tiny_development',
                    workload_stratum=selected['workload_stratum'], execution_sources=list(selected['sources']),
                    exposure='previously exposed facts and meaning; new original-author composition',
                    success=outcome['success'] and receipt['guard']['success'],status=outcome['status'],result=result,
                    worker=receipt['worker'],observations=receipt['observations'])
                sealed = write_once(root/'common-outcome.json',common)
                rows,normalization_spec = reference_for_case(case)
                reference = write_once(root/'reference.json',dict(schema_version='xgap-normalized-row-reference-v1',
                    question_id=common['question_id'],dataset=profile['dataset'],ordered=True,
                    rows=rows,normalization=normalization_spec))
                receipt['score'] = score_trial(sealed['path'],receipt_sha256=sealed['sha256'],
                    reference_path=reference['path'],reference_sha256=reference['sha256'],output=root/'score.json')
            receipt['success'] = receipt['composition_admitted']
    except (Exception,KeyboardInterrupt) as error:
        receipt.update(error_type=type(error).__name__, error=str(error))
    finally:
        receipt['processes'] = processes.close()
        for name,observer in observers.items():
            observer.close()
        if ports: ports.close()
        receipt['owned_groups_drained'] = all(not _group_sample(s.process.pid) for s in owned)
        receipt['all_owned_closed'] = (all(p['returncode'] is not None for p in receipt['processes']) and
            receipt['owned_groups_drained'] and all(not o.thread.is_alive() and o.inflight == 0 for o in observers.values()))
        receipt['success'] = receipt['success'] and receipt['all_owned_closed']
        if prior_key is None: os.environ.pop('XGAP_EXTERNAL_LLM_API_KEY',None)
        else: os.environ['XGAP_EXTERNAL_LLM_API_KEY'] = prior_key
        pin = write_once(root/'receipt.json',receipt)
    print(json.dumps(dict(success=receipt['success'],receipt=pin,error=receipt.get('error'))))
    return 0 if receipt['success'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('profile-path','profile-sha256','output'): parser.add_argument('--'+name,required=True)
    parser.add_argument('--read-key',action='store_true')
    parser.add_argument('--federation',choices=['fedup','fedx','single-fuseki'],default='fedup')
    parser.add_argument('--fedx-build')
    parser.add_argument('--case',choices=['single-source','cross-source'],default='cross-source')
    parser.add_argument('--compatibility',choices=['original','https-property-iris-v1',
                        'https-property-iris-qwen-key-v1','https-iris-qwen-key-v2'],default='original')
    raise SystemExit(check(**vars(parser.parse_args())))
