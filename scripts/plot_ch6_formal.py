#!/usr/bin/env python3
"""Render already-audited numerical figure cells, keeping every method visible.

Does not fetch results or impute missing points. C1 is supplied from its separate
actual trace table. Raw CSV/JSON values and evidence identities remain the source.
"""
import argparse
import json
from pathlib import Path

from xgap.experiments.ch6_formal_protocol import FIGURES,METHOD_ORDER,audit_observation

COLORS=dict(XGAP='#1464B4',NP='#E38B2C',SH='#419D78',GR='#9C6CB5',TS='#5D6770')


def plot(matrix_path,output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rows=json.loads(Path(matrix_path).read_text())['rows']
    for row in rows:audit_observation(row)
    root=Path(output);root.mkdir(parents=True,exist_ok=False)
    for figdef in FIGURES:
        if figdef.id=='C1':continue
        selected=[r for r in rows if r['figure']==figdef.id]
        # Separate timing/input populations rather than quietly joining them.
        groups=sorted({(r['deployment'],r['timing_scope']) for r in selected})
        fig,axes=plt.subplots(1,len(groups),figsize=(max(6,5*len(groups)),4.5),squeeze=False)
        from fractions import Fraction
        categorical=figdef.x in ('dataset','method')
        positions=list(range(len(figdef.levels))) if categorical else [float(Fraction(str(v))) for v in figdef.levels]
        for ax,group in zip(axes[0],groups):
            panel=[r for r in selected if (r['deployment'],r['timing_scope'])==group]
            notes=[]
            for method in METHOD_ORDER:
                series=[r for r in panel if r['method']==method]
                numeric={str(r['x_value']):r['value'] for r in series if r['value'] is not None}
                values=[numeric.get(str(v),float('nan')) for v in figdef.levels]
                if figdef.x=='method':
                    index=list(METHOD_ORDER).index(method)
                    ax.bar([index],[numeric.get(method,float('nan'))],color=COLORS[method],label=method)
                else:
                    style='--' if series and all(r['configuration_kind']=='fixed_reference' for r in series) else '-'
                    ax.plot(positions,values,style,marker='o',label=method,color=COLORS[method])
                missing=[r for r in series if r['value'] is None]
                if missing:
                    notes.append(method+': '+', '.join(sorted({r['status'] for r in missing})))
                elif not series:notes.append(method+': see other input/deployment panel')
            if figdef.id=='F3':
                ax.plot(positions,[float(Fraction(x)) for x in figdef.levels],':',color='black',label='epsilon reference')
            # A 2eta line is permitted only by the audited F6 selection record;
            # do not automatically print it for every method or missing pool.
            if figdef.id=='S1':ax.set_xscale('log');ax.set_yscale('log')
            ax.set_xticks(positions,list(map(str,figdef.levels)))
            ax.set_xlabel(figdef.x);ax.set_ylabel(figdef.y+' ('+figdef.unit+')')
            ax.set_title(' / '.join(group));ax.legend(fontsize=8)
            ax.text(0,-.3,'\n'.join(notes),transform=ax.transAxes,fontsize=7,va='top')
        fig.suptitle(figdef.id+'  '+figdef.caption);fig.tight_layout(rect=(0,.18,1,.96))
        fig.savefig(root/(figdef.id+'.pdf'),bbox_inches='tight');plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--matrix-path',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();plot(a.matrix_path,a.output)
