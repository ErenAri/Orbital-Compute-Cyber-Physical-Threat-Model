"""Generate all five v0.4.4 figures from results_v044.json and thermal_model.py."""
from __future__ import annotations
import json
import warnings
import numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
warnings.filterwarnings('ignore', message='This figure includes Axes that are not compatible with tight_layout')
from thermal_model import (
    P, duration_for, warmup_for, simulate, load_nominal, load_phase_locked,
    make_energy_matched_pair, make_energy_matched_solar_profile, in_hot_phase,
)

R=json.load(open('results_v044.json',encoding='utf-8'))
ACC='#b3541e'; ACC2='#1f4e79'; GRY='#8a8a8a'; FG='#1a1a1a'; GRN='#2e6b4f'; PUR='#7a4fa3'
plt.rcParams.update({'font.size':8,'axes.edgecolor':'#444','text.color':FG,
                     'xtick.color':FG,'ytick.color':FG,'axes.labelcolor':FG})
def clean(a):
    a.grid(alpha=.22,lw=.5)
    for s in ('top','right'): a.spines[s].set_visible(False)

DUR=duration_for(P,8)
fn_n, fn_a, _=make_energy_matched_pair(P,11,12,8,1.0)
s_nom=simulate(fn_n,P,duration=DUR,seed=11)
s_att=simulate(fn_a,P,duration=DUR,seed=12)

# Figure 1: mechanism in marginal reference configuration
pm=dict(P); pm.update(A_rad=80.0,eps=0.75)
fn_nm, fn_am, _=make_energy_matched_pair(pm,11,12,8,1.0)
nm=simulate(fn_nm,pm,duration=duration_for(pm,8),seed=11)
am=simulate(fn_am,pm,duration=duration_for(pm,8),seed=12)
w=(am['t']>=3*pm['period'])&(am['t']<=6*pm['period'])
th=(am['t'][w]-am['t'][w][0])/3600.; hot=in_hot_phase(am['t'][w],pm)
fig,ax=plt.subplots(2,1,figsize=(7.0,4.4),sharex=True,gridspec_kw={'height_ratios':[1,1.35],'hspace':.13})
for a,(lo,hi) in zip(ax,[(0,45),(40,100)]):
    a.fill_between(th,lo,hi,where=hot,color='#f2c14e',alpha=.16,lw=0); a.set_ylim(lo,hi); a.set_xlim(th[0],th[-1]); clean(a)
ax[0].plot(th,nm['P'][w]/1000,color=GRY,lw=1.0,label='Synthetic diversified load')
ax[0].plot(th,am['P'][w]/1000,color=ACC,lw=1.3,label='Synthetic phase-shaped load')
ax[0].set_ylabel('Compute power (kW)'); ax[0].legend(frameon=False,fontsize=7,loc='center left')
ax[0].set_title('Matched sampled orbit-average power, different peak thermal state',fontsize=9,loc='left',pad=6)
ax[1].axhline(90,color='#a11',ls='--',lw=.9); ax[1].axhline(75,color='#c86',ls=':',lw=.9)
ax[1].plot(th,nm['Tn'][w]-273.15,color=GRY,lw=1.0); ax[1].plot(th,am['Tn'][w]-273.15,color=ACC,lw=1.4)
ax[1].text(th[-1]*.995,91,'assumed model upper limit (90 °C)',ha='right',fontsize=6.5,color='#a11')
ax[1].text(th[-1]*.995,76,'assumed throttle threshold (75 °C)',ha='right',fontsize=6.5,color='#c86')
ax[1].set_ylabel('Node temperature (°C)'); ax[1].set_xlabel('Time (hours)')
plt.tight_layout(); plt.savefig('fig1_mechanism.png',dpi=200,bbox_inches='tight',facecolor='white'); plt.close()

# Figure 2: sensitivity design and parameter-class spans
rows=sorted([x for x in R['sensitivity_cases'] if 'consumed_K' in x],key=lambda x:x['consumed_K'])
fig,ax=plt.subplots(1,2,figsize=(7.0,3.3),gridspec_kw={'width_ratios':[1.65,1.0]})
case_colors={'single_factor':ACC,'joint':'#c98a5e','baseline_reference':GRY}
ax[0].barh([x['case'] for x in rows],[x['consumed_K'] for x in rows],color=[case_colors[x['case_type']] for x in rows],height=.58)
ax[0].axvline(R['baseline']['peak_delta_K'],color='#666',ls=':',lw=.8)
ax[0].set_xlabel('Observed peak-temperature difference (K)'); ax[0].tick_params(labelsize=6.2); clean(ax[0])
ax[0].set_title('12 sensitivity entries: 10 single-factor + 1 joint + baseline',fontsize=8.2,loc='left')
from matplotlib.patches import Patch
ax[0].legend(handles=[Patch(facecolor=ACC,label='single-factor'),Patch(facecolor='#c98a5e',label='joint A/ε'),Patch(facecolor=GRY,label='baseline reference')],frameon=False,fontsize=6.2,loc='lower right')
sp=R['sensitivity_summary']['parameter_group_spans_K']
groups=['radiator','capacitance','conductance','orbit_period','power']
labels=['radiator slice','node capacitance','loop conductance','orbit period','power assumptions']
vals=[sp[g]['span_K'] for g in groups]
y=np.arange(len(labels))
ax[1].barh(y,vals,color=[GRY,GRY,GRY,GRY,ACC],height=.58)
ax[1].set_yticks(y); ax[1].set_yticklabels(labels,fontsize=6.2); ax[1].invert_yaxis()
ax[1].set_xlabel('Within-group observed span (K)'); ax[1].tick_params(labelsize=6.3); clean(ax[1])
ax[1].set_title('Overall range is set by power-related cases',fontsize=8.0,loc='left')
for i,v in enumerate(vals): ax[1].text(v+.15,i,f'{v:.2f}',va='center',fontsize=6.3)
ax[1].set_xlim(0,max(vals)*1.12)
plt.tight_layout(); plt.savefig('fig4_margin_spread.png',dpi=200,bbox_inches='tight',facecolor='white'); plt.close()

# Figure 3: peak-matched synthetic trajectories
syn=R['synthetic_peak_matched']
sims={}
for name,item in syn.items():
    kw={item['parameter']:item['scale']}
    sims[name]=simulate(load_nominal,P,duration=DUR,seed=11,**kw)
wv=(s_att['t']>=3*P['period'])&(s_att['t']<=5.5*P['period']); tv=(s_att['t'][wv]-s_att['t'][wv][0])/3600.
fig,ax=plt.subplots(1,2,figsize=(7.0,2.8),gridspec_kw={'width_ratios':[1.7,1]})
ax[0].plot(tv,s_att['Tn'][wv]-273.15,color=ACC,lw=1.5,label='Induced phase-shaped load',zorder=5)
for (name,s),col in zip(sims.items(),[ACC2,GRN,PUR]):
    ax[0].plot(tv,s['Tn'][wv]-273.15,lw=1.0,color=col,label=f'Synthetic matched: {name}')
ax[0].axhline(R['baseline']['phase_locked']['peak_C'],color='#666',ls=':',lw=.8)
ax[0].set_ylabel('Node temperature (°C)'); ax[0].set_xlabel('Time (hours)'); ax[0].legend(frameon=False,fontsize=5.8,loc='lower left'); clean(ax[0])
ax[0].set_title('Peak matching does not match the temperature trajectory',fontsize=8.5,loc='left')
names=['induced\nload','emissivity','loop /\npump','env.\nflux']; rmse=[0]+[syn[k]['trajectory_rmse_K'] for k in syn]
ax[1].bar(names,rmse,color=[ACC,ACC2,GRN,PUR],width=.62); ax[1].set_ylabel('Trajectory RMSE vs\ninduced load (K)'); clean(ax[1]); ax[1].tick_params(labelsize=6.6)
ax[1].set_title('Peak is one scalar, not attribution',fontsize=8.5,loc='left')
plt.tight_layout(); plt.savefig('fig2_trajectories.png',dpi=200,bbox_inches='tight',facecolor='white'); plt.close()

# Figure 4: raw metric signatures + uncertainty AUC
metric={x['case']:x for x in R['candidate_metric_matrix']}
faults=['radiator emissivity','environmental flux','loop / pump','induced phase-locked load']
fig,ax=plt.subplots(1,2,figsize=(7.0,3.0),gridspec_kw={'width_ratios':[1.45,1]})
# Binary cells explicitly mean project-selected material shift, not detection.
M=np.array([[metric[f]['A_material_shift_project_threshold'],metric[f]['C_material_shift_project_threshold']] for f in faults],dtype=int)
ax[0].imshow(M,cmap=matplotlib.colors.ListedColormap(['#f0efec',GRN]),aspect='auto',vmin=0,vmax=1)
for i in range(M.shape[0]):
    for j in range(M.shape[1]):
        ax[0].text(j,i,'material\nshift' if M[i,j] else 'no material\nshift',ha='center',va='center',fontsize=6.4,color='white' if M[i,j] else '#777',fontweight='bold' if M[i,j] else 'normal')
ax[0].set_xticks([0,1]); ax[0].set_xticklabels(['A: energy\nbalance','C: gradient'],fontsize=6.8)
ax[0].set_yticks(range(4)); ax[0].set_yticklabels(['synthetic emissivity','synthetic environment','synthetic loop/pump','induced load'],fontsize=6.4)
for sp in ax[0].spines.values(): sp.set_visible(False)
ax[0].set_title('No tested single metric separates every modelled case',fontsize=8.3,loc='left')
auc=R['illustrative_uncertainty']['pairs']
ax[1].barh(['emissivity','environment','loop / pump'],[auc['radiator emissivity']['empirical_auc_fault_gt_induced'],auc['environmental flux']['empirical_auc_fault_gt_induced'],auc['loop / pump']['empirical_auc_fault_gt_induced']],color=[ACC2,PUR,GRN],height=.55)
ax[1].axvline(.5,color='#777',ls=':',lw=.8); ax[1].set_xlim(.4,1.0); ax[1].set_xlabel('Illustrative empirical AUC\n(fault residual > induced residual)'); clean(ax[1]); ax[1].tick_params(labelsize=7)
ax[1].set_title('Uncertainty analysis is illustrative,\nnot operational detector validation',fontsize=8.2,loc='left')
plt.tight_layout(); plt.savefig('fig3_detectors.png',dpi=200,bbox_inches='tight',facecolor='white'); plt.close()

# Figure 5: candidate phase-correlation feature and non-malicious thermal comparator
d=R['temporal_feature']['depth_sweep']; ben=R['temporal_feature']['benign_power_aware']
fig,ax=plt.subplots(1,2,figsize=(7.0,2.8))
ax[0].plot([x['depth']*100 for x in d],[x['rho'] for x in d],'o-',color=ACC,lw=1.3,ms=3.5)
ax[0].set_xlabel('Phase-shaping depth (%)'); ax[0].set_ylabel('Correlation ρ with hot phase'); ax[0].set_ylim(-.05,1.08); clean(ax[0])
a3=ax[0].twinx(); a3.plot([x['depth']*100 for x in d],[x['peak_C'] for x in d],'s--',color=GRY,lw=1.0,ms=3); a3.set_ylabel('Peak temperature (°C)',fontsize=7.5); a3.tick_params(labelsize=7); a3.spines['top'].set_visible(False)
ax[0].set_title('Controlled shaping sweep at matched sampled energy',fontsize=8.3,loc='left')
base=d[0]['peak_C']; d75=next(x for x in d if x['depth']==0.75); full=d[-1]
bar_names=['75% phase-\nshaped','power-aware\nbenign','full phase-\nshaped']
bar_exc=[d75['peak_C']-base, ben['peak_excursion_vs_diversified_K'], full['peak_C']-base]
bar_rho=[d75['rho'],ben['rho'],full['rho']]
ax[1].bar(bar_names,bar_exc,color=['#c98a5e',GRN,ACC],width=.62)
ax[1].set_ylabel('Peak excursion vs diversified (K)'); ax[1].tick_params(axis='x',labelsize=5.8); clean(ax[1]); ax[1].set_title('Non-malicious timing exercises most of the modelled effect',fontsize=7.7,loc='left')
for i,(v,r) in enumerate(zip(bar_exc,bar_rho)):
    ax[1].text(i,v+.22,f'{v:.2f} K\nρ={r:.3f}',ha='center',fontsize=6.1)
ax[1].text(.02,.025,f"Benign synthetic schedule = {ben['fraction_of_full_phase_excursion_pct']:.1f}% of full phase-shaped excursion",transform=ax[1].transAxes,fontsize=5.8,color='#555')
ax[1].set_ylim(0,max(bar_exc)*1.18)
plt.tight_layout(); plt.savefig('fig5_detectorB.png',dpi=200,bbox_inches='tight',facecolor='white'); plt.close()
print('generated fig1_mechanism.png fig4_margin_spread.png fig2_trajectories.png fig3_detectors.png fig5_detectorB.png')
