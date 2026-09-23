#!/usr/bin/env python3
"""Publish figure/design tables and an honest local readiness inventory, no runs."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
from datetime import datetime, timezone

from xgap.experiments.ch6_formal_protocol import registry,matrix,write_csv,pin_file
from xgap.experiments.one_shot_records import write_once

REPO=Path(__file__).resolve().parents[1]


def prepare(*,output,attachment,overall_panels='both',data_root='/Users/anthonyche/xgap-data'):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    source=pin_file(attachment);doc=registry();doc['source_attachment_sha256']=source['sha256']
    panels={'both':('native','rdf'),'rdf':('rdf',),'native':('native',)}[overall_panels]
    doc['overall_panels']=list(panels)
    pins={};pins['figure_contract']=write_once(root/'figure_contract.json',doc)
    rows=matrix(overall_panels=panels)
    write_csv(root/'evaluation_matrix.csv',rows);pins['evaluation_matrix']=pin_file(root/'evaluation_matrix.csv')
    pins['evaluation_matrix_json']=write_once(root/'evaluation_matrix.json',dict(rows=rows))
    figures=[dict(id=f['id'],caption=f['caption'],x_factor=f['x'],levels=f['levels'],y_metric=f['y'],
        unit=f['unit'],methods='XGAP, NP, SH, GR, TS',cohort=f['cohort'],track=f['track'],
        statistic=f['statistic'],notes=f['note']) for f in doc['figures']]
    write_csv(root/'figure_plan.csv',figures);pins['figure_plan']=pin_file(root/'figure_plan.csv')
    comparison_rows=[]
    for d in ('D1','D2','D3'):
        for w in ('W1','W2','W3','W4'):
            for panel in panels:
                for method in doc['method_order']:
                    comparison_rows.append(dict(dataset=d,workload=w,deployment=panel,method=method,
                        planned_cases=200,planned_cases_status='initial_target_not_power_or_resource_admitted',
                        repetitions=None,template_families=None,heldout_cases=None,
                        status='unsupported_deployment' if panel=='native' and method=='TS' else 'awaiting_frozen_test_split',
                        answer_em=None,answer_f1=None,e2e_ms=None,backend_calls=None,evidence_pin=None))
    write_csv(root/'overall_workload_matrix.csv',comparison_rows);pins['overall_workload_matrix']=pin_file(root/'overall_workload_matrix.csv')
    # Official source facts and previous development receipts are never relabeled
    # as a test split, a current method comparison, or a successful formal gate.
    known={}
    for name,relative in [('development','ch6-development-20260922-v1/preparation_receipt.json'),
        ('baseline_single','ch6-aruqula-single-source-20260922-v5/receipt.json'),
        ('baseline_cross','ch6-aruqula-fedx-20260922-v3/receipt.json'),
        ('finbench_rdf','finbench-sf01-rdf-tdb-20260913-v1/receipt.json')]:
        path=Path(data_root)/relative
        known[name]=pin_file(path) if path.is_file() else None
    disk=shutil.disk_usage(root)
    tasks=[
        ('test_split','Publish template-family-disjoint cases and independently computed references for D1/D2/D3.'),
        ('dataset_stores','Freeze actual D1/D2 evaluation snapshots; shared labeled RDF and native deployment identities.'),
        ('external_batch_gate','Exercise five-method shared RDF dispatch; never substitute internal Two-stage.'),
        ('factor_inputs','Admit actual N/u/source-count/graph-scale case bundles, with exact counts and invariant gold semantics.'),
        ('f6_cost_pool','Freeze equivalent complete-query plans and comparable offline costs; TS reference is conditional on Q equivalence.'),
        ('sample_budget','Freeze independent case count, repetitions, all-call/token/wall/disk limits after the bounded gate.'),
        ('release_audit','Require successful release audit with all asset pins, input identities and closure receipts.'),
    ]
    blockers=[dict(id=k,description=v,status='pending',evidence=None) for k,v in tasks]
    budget=dict(schema_version='xgap-ch6-budget-scenarios-v1',formal_authorization=False,
        methods=doc['method_order'],overall_cases_target=2400,rdf_cells_per_repetition=12000,
        native_cells_per_repetition=9600 if 'native' in panels else 0,
        external_calls_per_request_cap=64,external_model_calls_per_rdf_repetition_cap=2400*64,
        internal_calls_per_nl_request_cap=1,internal_model_calls_per_rdf_repetition_cap=2400*4,
        external_output_tokens_per_request_cap=64*2048,input_tokens_cap=None,
        request_wall_seconds=300,source_calls_per_request=256,source_timeout_seconds=20,
        model_money=None,pricing_known=False,actual_total_calls=0,
        sequential_rdf_hours_if_each_request_seconds={str(t):12000*t/3600 for t in (5,15,60,300)},
        all_figures_are_one_factor_sweeps=True,reused_figures=['E1/E2/F1/F2','E5/F5','F3/F4','F7/F8','S3/S4'],
        zero_calls_during_this_preparation=True,
        warning='These are ceilings/scenarios, not measured forecasts or an approved full-run budget. TS makes many calls per request.')
    pins['budget_scenarios']=write_once(root/'budget_scenarios.json',budget)
    audit=dict(schema_version='xgap-ch6-preparation-status-v1',timestamp=datetime.now(timezone.utc).isoformat(),
        source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        source_worktree_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=REPO)),
        figure_contract_ready=True,formal_campaign_ready=False,figures=21,methods=5,
        design_rows=len(rows),overall_workload_rows=len(comparison_rows),known_evidence=known,
        disk=dict(free_bytes=disk.free,reserve_bytes=6*1024**3,available_above_reserve=max(0,disk.free-6*1024**3)),
        remaining=blockers,model_calls=0,backend_calls=0,formal_results=0,
        scope='Prepared design and launch contracts; actual dataset/case/runtime gates remain independently verifiable.')
    pins['readiness']=write_once(root/'readiness.json',audit)
    write_once(root/'package.json',dict(schema_version='xgap-ch6-preparation-package-v1',source_attachment=source,artifacts=pins))
    print(json.dumps(dict(output=str(root),figures=21,design_rows=len(rows),formal_campaign_ready=False)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('output','attachment'):p.add_argument('--'+n,required=True)
    p.add_argument('--overall-panels',choices=['both','rdf','native'],default='both')
    p.add_argument('--data-root',default='/Users/anthonyche/xgap-data')
    prepare(**vars(p.parse_args()))
