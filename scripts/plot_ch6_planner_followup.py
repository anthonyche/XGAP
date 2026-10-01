"""Plot sealed before/after engineering observations, with quality changes visible."""
import argparse,csv
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

p=argparse.ArgumentParser();p.add_argument('--results',type=Path,required=True);root=p.parse_args().results
with (root/'cells.csv').open() as f:rows=list(csv.DictReader(f))
if len(rows)!=6:raise ValueError('Expected the frozen three-case engineering comparison')
groups={v:sorted([r for r in rows if r['version']==v],key=lambda r:r['question_id']) for v in ('before','after')}
if [r['question_id'] for r in groups['before']]!=[r['question_id'] for r in groups['after']]:raise ValueError('Unmatched cases')
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False})
fig,axes=plt.subplots(1,3,figsize=(11.5,4.5),layout='constrained')
labels=['Reachability','Transfer\nsummary','Company\nsummary'];x=np.arange(3)
for ax,key,title,scale in zip(axes,('planning_cpu_ms','total_online_ms','answer_f1'),
        ('Planning CPU (s)','Total online time (s)','Answer row F1'),(1000,1000,1)):
    for version,shift,color in [('before',-.18,'#b6c0cc'),('after',.18,'#357bb5')]:
        values=[float(r[key])/scale for r in groups[version]]
        bars=ax.bar(x+shift,values,.34,label=version.capitalize(),color=color)
        ax.bar_label(bars,fmt='%.2f',fontsize=8,padding=3)
    ax.set_xticks(x,labels);ax.set_title(title);ax.set_ylim(0,max(float(r[key])/scale for r in rows)*1.18)
axes[0].legend(frameon=False,fontsize=9)
fig.suptitle('XGAP controlled-input follow-up: same three inputs and ε = 1/3',fontweight='bold',fontsize=13)
fig.supxlabel('Fields disclosed: 3 → 2; clarification calls: 1 → 1; no certificate violations.\n'
    'One observation per version; interpretations may differ. Two empty references. Not a same-query speedup or an epsilon sweep.',fontsize=8.5)
for ext in ('png','pdf'):fig.savefig(root/('planner_followup.'+ext),dpi=170)
