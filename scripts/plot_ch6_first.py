"""Render sealed XGAP-only pilot metrics; never executes an experimental cell."""
import argparse
import csv,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
parser=argparse.ArgumentParser()
parser.add_argument('--results',required=True,type=Path)
args=parser.parse_args()
root=args.results
with (root/'cells.csv').open() as f:rows=list(csv.DictReader(f))
nl=sorted([r for r in rows if r['track']=='nl'],key=lambda r:r['question_id'])
if len(nl)!=6 or any(r['method']!='xgap-unified-lookahead' for r in nl):
 raise ValueError('This frozen pilot figure expects six XGAP NL cells')
titles={'temporal_reachability':'Reachability','outgoing_transfer_summary':'Transfer sum/count','company_transfer_summary':'Company transfers'}
x=np.arange(len(nl));labels=[titles[r['template']]+'\n'+r['stratum'] for r in nl]
planning=np.array([float(r['planning_ms'])/1000 for r in nl]);execution=np.array([float(r['execution_ms'])/1000 for r in nl]);total=np.array([float(r['total_online_ms'])/1000 for r in nl]);other=total-planning-execution
assert all(other>=0)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
fig,(ax,bx)=plt.subplots(2,1,figsize=(10.5,7.5),height_ratios=[1.15,1],layout='constrained')
ax.bar(x,planning,label='Policy planning (wall)',color='#3478b8',width=.63)
ax.bar(x,execution,bottom=planning,label='Final execution',color='#65a78b',width=.63)
ax.bar(x,other,bottom=planning+execution,label='LLM + initialization + recording (residual)',color='#c3cbd4',width=.63)
for i,v in enumerate(total):ax.text(i,v+.5,f'{v:.1f}s',ha='center',fontsize=9)
ax.set_ylim(0,max(total)+5);ax.set_ylabel('Observed online time (s)');ax.set_xticks(x,labels);ax.legend(frameon=False,fontsize=8.5,loc='lower left',bbox_to_anchor=(0,1.0),ncol=3)
ax.set_title('XGAP: six real NL requests on FinBench SF0.1',loc='left',fontweight='bold',pad=33)
mb=[float(r['transfer_payload_bytes'])/1e6 for r in nl];bx.bar(x,mb,color='#a583b6',width=.63)
for i,(v,r) in enumerate(zip(mb,nl)):
 bx.text(i,v+1,f'{v:.1f} MB\n{r["backend_http_attempts"]} calls; {r["expected_rows"]} answer rows',ha='center',fontsize=9)
bx.set_ylim(0,max(mb)+13);bx.set_ylabel('Source request + response payload (MB)');bx.set_xticks(x,labels)
bx.set_title('All six answers match the independent reference; three references are empty',loc='left',fontsize=11,pad=12)
fig.supxlabel('One observation per question; three authored template families. No external baseline comparison or speedup claim.',fontsize=9)
for suffix in ('png','pdf'):fig.savefig(root/('xgap_first_real.'+suffix),dpi=170)
print(json.dumps({'figure':str(root/'xgap_first_real.png'),'pdf':str(root/'xgap_first_real.pdf')}))
