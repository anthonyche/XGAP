#!/usr/bin/env python3
"""Render measured E1/E2/E7/E8 FinBench panels from a sealed analysis only.

Run in the existing plotting Python environment; no method/model/backend imports.
These four panels do not stand in for the unfinished three-dataset, 20-figure set.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

METHODS=('xgap-bounded-joint-exact','xgap-bounded-joint-performance')
FRAMES=('all_ids','active_anchors')
SPECS=(
    ('E1','latency_ms',.001,'Mean end-to-end latency (s)','Common completed cases'),
    ('E2','backend_response_bytes',1/1024**2,'Mean backend transfer\n(MiB/request)','All planned requests'),
    ('E7','correct_completion',100,'Correct completion rate (%)','All planned requests'),
    ('E8','coverage',100,'Answer coverage (%)','All planned requests'),
)


def pin(path):
    path=Path(path).resolve()
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size)


def render(*,summary_path,summary_sha256,output):
    summary_pin=pin(summary_path)
    if summary_pin['sha256']!=summary_sha256:raise ValueError('Analysis checksum differs')
    summary=json.loads(Path(summary_path).read_text())
    if summary.get('schema_version')!='xgap-ch7-primary-analysis-v1' or not summary.get('primary_batch_complete'):
        raise ValueError('Complete, closed formal primary analysis required before plotting')
    if pin(summary['metrics']['path'])!=summary['metrics']:raise ValueError('Measured table checksum differs')
    if summary['deployment']!='native_neo4j_fuseki':raise ValueError('Do not merge native and RDF deployments')
    rows={(s['stratum'],s['method']):s for s in summary['summaries']}
    if len(rows)!=4 or set(rows)!={(s,m) for s in FRAMES for m in METHODS}:
        raise ValueError('Exactly the two frozen frames and two admitted methods are required')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':9,'axes.titlesize':10,'axes.labelsize':9,'xtick.labelsize':9,
        'ytick.labelsize':9,'legend.fontsize':9,'pdf.fonttype':42,'ps.fonttype':42})
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False);artifacts=[];missing=[]
    for figure_id,metric,scale,label,cohort in SPECS:
        if any(s[metric]['mean'] is None for s in rows.values()):
            missing.append(dict(figure=figure_id,reason='Missing measured values; not imputed'))
            continue
        table=[]
        for frame in FRAMES:
            for method in METHODS:
                s=rows[frame,method];value=s[metric];interval=value['ci95']
                table.append(dict(figure=figure_id,dataset='FinBench SF0.1 derived',deployment=summary['deployment'],
                    frame=frame,method=method,mean=value['mean']*scale,
                    ci95_low=interval[0]*scale if interval else None,ci95_high=interval[1]*scale if interval else None,
                    interval_method=value['interval'],families=value['families'],records=value['records'],
                    planned=s['planned'],correct=s['correct'],answered=s['answered'],
                    common_completion_cases=s['common_completion_cases'],empty_references=s['empty_references'],
                    cohort=cohort,metric=metric,unit=label))
        csv_path=root/(figure_id+'_FinBench_native.csv')
        with csv_path.open('x',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(table[0]),lineterminator='\n');writer.writeheader();writer.writerows(table)
        fig,axes=plt.subplots(1,2,figsize=(7.0,2.9),sharey=True)
        for ax,frame,title in zip(axes,FRAMES,('All-ID sample','Active-anchor sample')):
            subset=[r for r in table if r['frame']==frame]
            means=[r['mean'] for r in subset]
            bars=ax.bar([0,1],means,width=.56,color=['#0072B2','#E69F00'],edgecolor='#222222',linewidth=.6)
            bars[1].set_hatch('///')
            for i,r in enumerate(subset):
                if r['ci95_low'] is not None:
                    ax.errorbar(i,r['mean'],yerr=[[max(0,r['mean']-r['ci95_low'])],
                        [max(0,r['ci95_high']-r['mean'])]],fmt='none',ecolor='#111111',capsize=3,elinewidth=.9)
            ax.set_title(title);ax.set_xticks([0,1],['Exact','Performance']);ax.set_xlabel('Method')
            ax.set_axisbelow(True);ax.yaxis.grid(True,color='#dddddd',linewidth=.5)
            ax.spines[['top','right']].set_visible(False)
            planned=subset[0]['planned'];common=subset[0]['common_completion_cases']
            ax.text(.5,-.31,f'{planned} requests/method; {common} common completions',
                transform=ax.transAxes,ha='center',va='top',fontsize=8)
        axes[0].set_ylabel(label)
        upper=max(r['ci95_high'] if r['ci95_high'] is not None else r['mean'] for r in table)
        axes[0].set_ylim(0,105 if scale==100 else max(1,upper*1.18))
        fig.suptitle('FinBench SF0.1 derived · Neo4j + Fuseki',fontsize=10,y=.98)
        fig.subplots_adjust(left=.12,right=.98,bottom=.31,top=.82,wspace=.15)
        stem=root/(figure_id+'_FinBench_native')
        fig.savefig(str(stem)+'.pdf');fig.savefig(str(stem)+'.png',dpi=180)
        plt.close(fig)
        artifacts.append(dict(figure=figure_id,data=pin(csv_path),pdf=pin(str(stem)+'.pdf'),preview=pin(str(stem)+'.png')))
    manifest=dict(schema_version='xgap-ch7-primary-figures-v1',analysis=summary_pin,renderer=pin(__file__),
        matplotlib_version=matplotlib.__version__,artifacts=artifacts,missing_metrics=missing,
        full_chapter7_complete=False,scope='Four FinBench native primary panels only; frames are separate; other datasets and matched-RDF external comparisons pending')
    (root/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(manifest=pin(root/'manifest.json'),figures=len(artifacts))))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('summary-path','summary-sha256','output'):p.add_argument('--'+name,required=True)
    render(**vars(p.parse_args()))
