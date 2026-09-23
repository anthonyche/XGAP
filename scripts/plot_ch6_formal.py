#!/usr/bin/env python3
"""Render already-audited numerical figure cells, keeping every method visible.

Does not fetch results or impute missing points. C1 uses its separately pinned
actual trace table, or explicit missing panels. Raw values remain the source.
"""
import argparse
import json
from pathlib import Path

from xgap.experiments.ch6_formal_protocol import FIGURES,METHOD_ORDER,audit_observation,load_pin

COLORS=dict(XGAP='#1464B4',NP='#E38B2C',SH='#419D78',GR='#9C6CB5',TS='#5D6770')


def plot(matrix_path,output,case_trace_path=None,case_trace_sha256=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rows=json.loads(Path(matrix_path).read_text())['rows']
    for row in rows:audit_observation(row)
    root=Path(output);root.mkdir(parents=True,exist_ok=False)
    trace=None
    if bool(case_trace_path)!=bool(case_trace_sha256):raise ValueError('Trace path and hash required together')
    if case_trace_path:
        trace=load_pin(dict(path=case_trace_path,sha256=case_trace_sha256))
        if trace['schema_version']!='xgap-ch6-case-trace-v1' or set(trace['methods'])!=set(METHOD_ORDER):
            raise ValueError('C1 requires the five-method realized trace export')
    for figdef in FIGURES:
        if figdef.id=='C1':
            fig,axes=plt.subplots(5,1,figsize=(10,12),squeeze=False)
            shared_labels=list(dict.fromkeys(e['action_state'] for m in METHOD_ORDER
                for e in (trace['methods'][m]['events'] if trace else [])))
            display_labels={'binding':'Clarify','transform':'Plan rewrite','execute':'Execute','probe':'Probe','metadata':'Metadata'}
            for ax,method in zip(axes[:,0],METHOD_ORDER):
                item=trace['methods'][method] if trace else dict(status='pending',events=[])
                events=item['events'];labels=shared_labels
                if events:
                    if any(e.get('realized') is not True or e['method']!=method or not e.get('evidence_pin') for e in events):
                        raise ValueError('C1 accepts only evidenced realized actions')
                    ax.plot([e['round'] for e in events],[labels.index(e['action_state']) for e in events],
                            '-o',color=COLORS[method],label=method)
                    ax.set_yticks(range(len(labels)),[display_labels.get(x,x) for x in labels])
                    ax.set_xticks([e['round'] for e in events])
                else:
                    ax.text(.5,.5,item['status']+' — no sealed realized trace',ha='center',va='center',transform=ax.transAxes)
                    ax.set_yticks([]);ax.set_xticks([])
                ax.set_title(method,loc='left',color=COLORS[method]);ax.set_xlabel('Actual round');ax.set_ylabel('Action/state')
                ax.grid(axis='x',alpha=.15)
            fig.suptitle('C1  Realized actions'+(' — '+trace['question_id'] if trace else ' — pending'))
            fig.tight_layout(rect=(0,0,1,.97));fig.savefig(root/'C1.pdf',bbox_inches='tight');plt.close(fig)
            continue
        selected=[r for r in rows if r['figure']==figdef.id]
        # Separate timing/input populations rather than quietly joining them.
        group_key=lambda r:(r['deployment'],r['timing_scope'],r.get('stratum','declared cohort'))
        groups=sorted({group_key(r) for r in selected})
        fig,axes=plt.subplots(1,len(groups),figsize=(max(6,5*len(groups)),4.5),squeeze=False)
        from fractions import Fraction
        categorical=figdef.x in ('dataset','method')
        positions=list(range(len(figdef.levels))) if categorical else [float(Fraction(str(v))) for v in figdef.levels]
        for ax,group in zip(axes[0],groups):
            panel=[r for r in selected if group_key(r)==group]
            notes=[]
            for method in METHOD_ORDER:
                series=[r for r in panel if r['method']==method]
                if len({str(r['x_value']) for r in series})!=len(series):
                    raise ValueError('Multiple cohorts cannot overwrite the same plotted method/level')
                numeric={str(r['x_value']):r['value'] for r in series if r['value'] is not None}
                values=[numeric.get(str(v),float('nan')) for v in figdef.levels]
                if figdef.x=='method':
                    index=list(METHOD_ORDER).index(method)
                    ax.bar([index],[numeric.get(method,float('nan'))],color=COLORS[method],label=method)
                else:
                    style='--' if series and all(r['configuration_kind']=='fixed_reference' for r in series) else '-'
                    ax.plot(positions,values,style,marker='o',label=method,color=COLORS[method])
                for row in series:
                    low,high=row.get('ci_low'),row.get('ci_high')
                    if row['value'] is not None and low is not None and high is not None:
                        pos=positions[list(map(str,figdef.levels)).index(str(row['x_value']))]
                        ax.vlines(pos,low,high,color=COLORS[method],alpha=.8)
                        ax.plot([pos,pos],[low,high],linestyle='none',marker='_',color=COLORS[method])
                missing=[r for r in series if r['value'] is None]
                if numeric and group[0]=='mixed':
                    notes.append(method+': support '+', '.join(str(r['x_value'])+'='+str(r['supported_cases'])+'/'+str(r['total_cases'])
                                for r in series if r['value'] is not None))
                if missing:
                    notes.append(method+': '+', '.join(sorted({r['status'] for r in missing})))
                elif not series:notes.append(method+': see other input/deployment panel')
            if figdef.id=='F3':
                ax.plot(positions,[float(Fraction(x)) for x in figdef.levels],':',color='black',label='epsilon reference')
            # A 2eta line is permitted only by the audited F6 selection record;
            # do not automatically print it for every method or missing pool.
            if figdef.id=='S1':
                ax.set_xscale('log');ax.set_yscale('log')
                if not any(r['value'] is not None and r['value']>0 for r in panel):
                    ax.set_ylim(1,10)  # Axis viewport only; no fabricated observation.
                    notes.append('No positive measured values available on the log axis.')
            ax.set_xticks(positions,list(map(str,figdef.levels)))
            ax.set_xlabel(figdef.x);ax.set_ylabel(figdef.y+' ('+figdef.unit+')')
            ax.set_title(' / '.join(group));ax.legend(fontsize=8)
            ax.text(0,-.3,'\n'.join(notes),transform=ax.transAxes,fontsize=7,va='top')
        fig.suptitle(figdef.id+'  '+figdef.caption);fig.tight_layout(rect=(0,.18,1,.96))
        fig.savefig(root/(figdef.id+'.pdf'),bbox_inches='tight');plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--matrix-path',required=True);p.add_argument('--output',required=True)
    p.add_argument('--case-trace-path');p.add_argument('--case-trace-sha256')
    a=p.parse_args();plot(**vars(a))
