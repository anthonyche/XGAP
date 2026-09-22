"""Non-executable pilot/budget and figure registry. Does not launch any cells."""
import argparse
import hashlib
import json
import platform
import shutil
import subprocess
from pathlib import Path
from collections import Counter


def pin(p):
    p=Path(p);h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return dict(path=str(p),sha256=h.hexdigest(),bytes=p.stat().st_size)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--development',type=Path,required=True);ap.add_argument('--intake',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    def write(n,d): (args.output/n).write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n')
    datasets={d:json.loads((args.development/d/'dataset_manifest.json').read_text()) for d in ('D1','D2','D3')}
    provider_path=Path('/Users/anthonyche/xgap-data/finbench-sf01-serving-20260913-v1/native-profile-v2/profile.json')
    profile=json.loads(provider_path.read_text())
    provider=profile['modes']['performance']['provider']
    model={k:v for k,v in provider.items() if k in ('base_url','model','temperature','top_p','max_tokens','timeout_seconds','disable_thinking','prompt')}
    model.update(source_profile=pin(provider_path),status='previous frozen configuration; no API call this turn',
                 service_returned_model=None,inference_hardware=None,checkpoint=None,new_three_domain_prompt='not frozen')
    baseline=Path('/Users/anthonyche/xgap-data/unified-external-admission-20260921-v5/receipt.json')
    inventory=dict(schema_version='xgap-ch6-inventory-v1',code_base_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        created='2026-09-22',host=dict(os=platform.platform(),architecture=platform.machine(),coordinator='Python',
            python=platform.python_version(),physical_memory_bytes=int(subprocess.check_output(['sysctl','-n','hw.memsize'],text=True)),
            cpu=subprocess.check_output(['sysctl','-n','machdep.cpu.brand_string'],text=True).strip(),
            disk_free_bytes=shutil.disk_usage(args.output).free),datasets=datasets,
        d2_amendment='User authorized alternate source; MovieLens development, stable 20M proposed for evaluation; Wikidata not mapped',
        source_pins={p.name:json.loads(p.read_text()) for p in args.intake.glob('*-commit-pin.json')},
        limits=dict(candidate_cap=64,depth_cap=4,horizon_cap=64,large_N_admission=False),qwen_api=model,
        services=dict(neo4j='existing FinBench deployment; no D1/D2 native load or current health check',
            fuseki='existing FinBench deployment; new mini checks used RDFLib only'),
        external_baseline=dict(prior_receipt=pin(baseline),status='unsupported VALUES/OpTable in pinned original composition; no rerun',
            applicable_new_datasets='not_admitted'),model_calls_this_preparation=0,backend_network_calls_this_preparation=0)
    write('inventory.json',inventory)
    main_cases=3*4*24;main_runs=main_cases*3
    groups={
      'main':dict(track='NL-native',methods=['XGAP','Two-stage','LLM-direct'],cases_per_domain_stratum=24,repeat=1,figures=['E1','E2','F1','F2']),
      'N':dict(track='controlled-native',levels=[8,16,32,64],methods=['XGAP','Two-stage','greedy'],figures=['E3']),
      'u':dict(track='controlled-native',levels=[1,2,3,5,8],methods=['XGAP','Two-stage','greedy'],figures=['E4']),
      'D':dict(track='controlled-native',levels=[1,2,3,4],methods=['XGAP'],figures=['E5','F5']),
      'H':dict(track='controlled-native',levels=[2,4,8,12,16],methods=['XGAP','shallow'],figures=['E6']),
      'probe_price':dict(track='controlled-native',levels=[.1,.5,1,2,5],methods=['XGAP','noProbe'],figures=['E7']),
      'clarification_price':dict(track='controlled-native',levels=[.1,.5,1,2,5],methods=['XGAP','Two-stage'],figures=['E8']),
      'epsilon':dict(track='controlled-native',levels=['0','1/6','1/3','1/2','1'],methods=['XGAP','Two-stage'],figures=['F3','F4']),
      'variant':dict(track='controlled-native',levels=['default'],methods=['XGAP','noProbe','shallow','greedy'],figures=['F7','F8']),
      'eta':dict(track='offline_fixed_query_selector',levels=None,methods=['fixed retained pool selector'],figures=['F6']),
      'scale':dict(track='controlled-native',levels=None,methods=['XGAP','Two-stage'],figures=['S1','S2','S3','S4'])}
    configurations=sum(len(g['levels'])*len(g['methods']) for g in groups.values() if g.get('levels'))
    controlled_runs=configurations*3*4*2
    pilot=dict(schema_version='xgap-ch6-pilot-proposal-v1',runnable=False,authorization='not_requested; no paid or backend run scheduled',
        datasets=['D1','D2-MovieLens','D3'],defaults=dict(D=2,H=12,N=8,u=3,K=4,epsilon='1/3',backup='max'),
        groups=groups,development_excluded_from_pilot=True,allocation='same protocol per domain and W stratum',
        proposed_controlled_cases_per_domain_stratum=2,main_requests=main_runs,main_distinct_cases=main_cases,
        controlled_upper_bound_before_default_reuse=controlled_runs,
        reuse='D=1 is shallow; same case/config/seed/snapshot cell reused across plots and default points',
        one_dimensional_scans=True,cache_protocol='pending pilot admission; identical across methods',
        blockers=['D1/D2 new Neo4j+Fuseki mappings/load and small interface gates',
            'stable MovieLens 20M snapshot/scale and optional P345 frozen mapping',
            'FinBench official query-card fidelity for TSR1/TCR1/TCR4/TCR12',
            'LC-QuAD typed instantiation to compact lowering allowlist still requires domain bridge',
            'template diversity and true NL fixed-constraint wording audit; development prose is not pilot NL',
            'frozen private user coverage attestation and new controlled worker materialization',
            'actual probe/metadata targets, retained equivalent plans per template',
            'LLM-direct batch publisher integration and new three-domain one-call prompt hashes',
            'common measurable cost weights, total request caps, method order, pilot API authorization',
            'N/u feasible cohorts and S1 >64 representation admission; do not invent levels'])
    write('pilot_manifest.json',pilot)
    budget=dict(status='proposal_not_authorization',api_calls_upper_bound_main=main_runs,controlled_model_calls=0,
        output_token_cap_assumption=4096,output_tokens_upper_bound=main_runs*4096,input_tokens=None,
        illustrative_input_tokens_if_mean_3000=main_runs*3000,illustrative_not_measured=True,
        wall_hours_main_if_mean_request_seconds={str(s):main_runs*s/3600 for s in (5,15,60,180)},
        controlled_requests_upper_bound=controlled_runs,controlled_wall_hours_if_mean_seconds={str(s):controlled_runs*s/3600 for s in (1,5,15)},
        backend_calls_cap_assumption=100,backend_calls_absolute_ceiling=(main_runs+controlled_runs)*100,
        backend_timeout_start_seconds=60,request_timeout_proposal_seconds=180,concurrency_proposal=1,
        model_money=None,reason_money_unknown='API pricing not supplied',full_study_budget=None,
        disk=dict(free_bytes=inventory['host']['disk_free_bytes'],reserve_floor_bytes=6*1024**3,
            movielens20m_compressed_download_page_estimate_bytes=190*1000**2,
            expanded_native_rdf_store_bytes=None,trace_bytes_if_1MiB_per_request=(main_runs+controlled_runs)*1024**2,
            note='No large download/load until manifest and actual disk capacity gate; stream compressed trial evidence'))
    write('budget_estimate.json',budget)
    text=Path('docs/ch6_experiment_plan_20260922.md').read_text();figures=[]
    import re
    for line in text.splitlines():
        match=re.match(r'\| ((?:E|F|S)[1-8]) \|',line)
        if match:
            cells=[v.strip() for v in line.strip('|').split('|')]
            figures.append(dict(id=cells[0],title=cells[1],x_factor=cells[2],series=cells[3],purpose=cells[4:],
                output='figures/'+cells[0]+'.pdf',status='planned_no_data_no_plot'))
    figures.extend(dict(id=i,status='planned_no_data_no_plot',output='figures/'+i+'.pdf') for i in ('C1','T1'))
    write('figure_registry.json',figures)
    write('seal.json',{p.name:pin(p) for p in args.output.iterdir() if p.is_file()})
    print(json.dumps(dict(output=str(args.output),main_requests=main_runs,controlled_upper_bound=controlled_runs,runnable=False)))

if __name__=='__main__':main()
