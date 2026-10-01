#!/usr/bin/env python3
"""Descriptive plots from sealed cells; no inference, method calls or fitting."""
import argparse
import json
from pathlib import Path
from statistics import median

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np


def plot(cells, output):
    rows=json.loads(Path(cells).read_text()); root=Path(output);root.mkdir(exist_ok=False)
    plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':160})
    near=[r for r in rows if r['round']=='first' and r['scenario']=='near_cluster']
    labels=['search_exact','search_025','search_050']; ticks=['Exact\n0','Performance\n0.25','Performance\n0.50']
    cohorts=[[r for r in near if r['label']==label] for label in labels]
    assert all(len(c)==4 and all(r['observation_class']=='method_observed' for r in c) for c in cohorts)
    answered=[[r for r in c if r['answered']] for c in cohorts]
    fields=[median(r['disclosed_coordinates'] for r in c) for c in answered]
    coverage=[len(c)/4 for c in answered]; correct=[sum(r['answer_em'] for r in c)/4 for c in cohorts]
    f1=[sum(r['answer_f1'] for r in c)/len(c) for c in answered]
    fig,axes=plt.subplots(1,3,figsize=(12.5,4.7)); x=np.arange(3)
    axes[0].bar(x,fields,color=['#53667e','#168c85','#ec9653'])
    for i,v in enumerate(fields):axes[0].text(i,v+.12,f'{v:g}',ha='center')
    axes[0].set(title='Information acquired',ylabel='Disclosed fields (answered median)',ylim=(0,5))
    axes[1].bar(x-.18,coverage,.36,label='Returned an answer',color='#78aaa3')
    axes[1].bar(x+.18,correct,.36,label='Entire answer correct',color='#274d74')
    for i in range(3):
        axes[1].text(i-.18,coverage[i]+.025,f'{round(coverage[i]*4)}/4',ha='center',fontsize=9)
        axes[1].text(i+.18,correct[i]+.025,f'{round(correct[i]*4)}/4',ha='center',fontsize=9)
    axes[1].set(title='Coverage and correctness',ylabel='Fraction of the same four tasks',ylim=(0,1.35));axes[1].legend(fontsize=8,loc='upper center')
    axes[2].bar(x,f1,color=['#53667e','#168c85','#ec9653'])
    for i,v in enumerate(f1):axes[2].text(i,v+.03,f'{v:.3f}',ha='center')
    axes[2].set(title='Answer-row quality',ylabel='Mean F1, conditional on answering',ylim=(0,1.2))
    for ax in axes:ax.set_xticks(x,ticks);ax.set_xlabel('Mode and declared epsilon')
    fig.suptitle('Similar intents: less confirmation can help, but looser tolerance can lose answers',fontsize=14)
    fig.text(.5,.018,'4 authored tasks on SF0.1. Full clarification matches Exact; fixed order matches Performance here.\nOne task permits no clarification. Intent-distance bounds do not bound answer error.',ha='center',fontsize=10)
    fig.tight_layout(rect=(0,.12,1,.94));fig.savefig(root/'near_cluster.png');fig.savefig(root/'near_cluster.pdf');plt.close(fig)

    part=[r for r in rows if r['round']=='first' and r['scenario']=='partial_information' and r['group_index'] in (4,5,6)]
    labels=['search_exact','full','search_025','fixed_025','search_050','fixed_050']
    names=['Exact search','Full clarification','Search, epsilon 0.25','Fixed order, epsilon 0.25','Search, epsilon 0.50','Fixed order, epsilon 0.50']
    colors=['#53667e','#7d8b9a','#99c8c0','#c2d8d3','#007f76','#ec9653'];fig,ax=plt.subplots(figsize=(12,5))
    x=np.arange(3);width=.12
    for j,label in enumerate(labels):
        cohort=sorted((r for r in part if r['label']==label),key=lambda r:r['group_index'])
        assert len(cohort)==3 and all(r['observation_class']=='method_observed' for r in cohort)
        positions=x+(j-2.5)*width
        for pos,r in zip(positions,cohort):
            if r['answered']:
                assert r['answer_em']==1
                ax.bar(pos,r['disclosed_coordinates'],width*.9,color=colors[j])
                ax.text(pos,r['disclosed_coordinates']+.05,f"{r['clarification_calls']}x",ha='center',fontsize=8)
            else:ax.scatter(pos,.07,marker='x',color=colors[j],s=40)
    ax.set_xticks(x,['Task 1','Task 2','Task 3: only ONE field allowed'])
    ax.set(ylabel='Disclosed fields (x above bar = clarification calls)',ylim=(0,4.5),title='Choosing the right clarification matters under a tight information budget')
    ax.legend(handles=[Patch(facecolor=color,label=name) for color,name in zip(colors,names)],ncol=3,fontsize=9,loc='upper center');ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    fig.text(.5,.015,'All returned answers in these three tasks are correct. A cross at zero means no answer, not a free correct answer.\nOnly the first three fully observed tasks are shown; task 4 was censored before all methods finished.',ha='center',fontsize=10)
    fig.tight_layout(rect=(0,.12,1,1));fig.savefig(root/'partial_information.png');fig.savefig(root/'partial_information.pdf');plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cells',required=True);p.add_argument('--output',required=True)
    plot(**vars(p.parse_args()))
