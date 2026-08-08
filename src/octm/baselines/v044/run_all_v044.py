"""Authoritative experiment pipeline for OCTM/TSM-01 v0.4.4.

This is the only script that generates normative numerical results for v0.4.4.
Legacy v0.4/v0.4.3 predecessor scripts are intentionally excluded from the release package.
"""
from __future__ import annotations
import json, platform, sys
import numpy as np
from thermal_model import (
    P, SIGMA, duration_for, warmup_for, simulate, load_nominal, load_phase_locked,
    make_energy_matched_pair, make_blend, make_energy_matched_solar_profile, energy_balance_residual,
    apparent_conductance, phase_correlation, peak_stats, in_hot_phase,
    threshold_excursion_windows, local_rise_rate, phase_lock_is_feasible,
)

N_ORBITS = 8
BASE_SEED_N = 11
BASE_SEED_A = 12


def run_pair(p, dt=1.0):
    dur = duration_for(p, N_ORBITS)
    fn_n, fn_a, _ = make_energy_matched_pair(p, BASE_SEED_N, BASE_SEED_A, N_ORBITS, dt)
    sn = simulate(fn_n, p, duration=dur, dt=dt, seed=BASE_SEED_N)
    sa = simulate(fn_a, p, duration=dur, dt=dt, seed=BASE_SEED_A)
    n = peak_stats(sn, p); a = peak_stats(sa, p)
    delta_e = 100.0 * (a['orbit_avg_kW'] / n['orbit_avg_kW'] - 1.0)
    return sn, sa, n, a, delta_e


def match_fault(target_peak, key, lo, hi, p=P):
    """Construct a synthetic physical-fault case matched to target peak."""
    dur = duration_for(p, N_ORBITS)
    for _ in range(32):
        mid = 0.5 * (lo + hi)
        st = peak_stats(simulate(load_nominal, p, duration=dur, seed=BASE_SEED_N,
                                 **{key: mid}), p)
        if st['peak_C'] < target_peak:
            if key == 'q_scale': lo = mid
            else: hi = mid
        else:
            if key == 'q_scale': hi = mid
            else: lo = mid
    val = 0.5 * (lo + hi)
    sim = simulate(load_nominal, p, duration=dur, seed=BASE_SEED_N, **{key: val})
    return val, sim, peak_stats(sim, p)


def prepare_residual_components(sim, p, N, seed, sensor_noise=0.3):
    """Precompute orbit-aggregated measurement terms for fast Monte Carlo.

    Uses common-random-number sensor perturbations for controlled comparisons.
    Each output array has one value per Monte Carlo draw and already averages
    across complete post-warmup orbits.
    """
    rng = np.random.default_rng(seed)
    dt = sim['t'][1] - sim['t'][0]
    n_per = int(round(p['period'] / dt))
    i0 = int(round(warmup_for(p) / dt))
    starts = list(range(i0, len(sim['t']) - n_per, n_per))
    rad_sum = np.zeros(N); dstore_sum = np.zeros(N)
    env_sum = 0.0; power_sum = 0.0
    for i in starts:
        sl = slice(i, i + n_per)
        # Measurement-noise arrays are generated per complete orbit then reduced.
        nr = rng.normal(0, sensor_noise, (N, n_per))
        trm = sim['Tr'][sl][None, :] + nr
        rad_sum += SIGMA * p['A_rad'] * np.mean(trm**4 - p['T_space']**4, axis=1)

        nTn0 = rng.normal(0, sensor_noise, N); nTn1 = rng.normal(0, sensor_noise, N)
        nTr0 = rng.normal(0, sensor_noise, N); nTr1 = rng.normal(0, sensor_noise, N)
        dstore_sum += (
            p['C_node'] * ((sim['Tn'][i+n_per] + nTn1) - (sim['Tn'][i] + nTn0))
            + p['C_rad'] * ((sim['Tr'][i+n_per] + nTr1) - (sim['Tr'][i] + nTr0))
        ) / p['period']
        env_sum += float(np.mean(np.asarray([float(x) for x in
                    (np.where(in_hot_phase(sim['t'][sl], p), p['q_hot'], p['q_cold']))])) * p['A_rad'])
        power_sum += float(np.mean(sim['P'][sl]))
    k = len(starts)
    return dict(
        rad_basis=rad_sum / k,
        dstore=dstore_sum / k,
        env_basis=env_sum / k,
        power_basis=power_sum / k,
    )


def residual_distribution(comp, p, d_rad, d_pcal, d_env):
    return (
        p['eps'] * (1.0 + d_rad) * comp['rad_basis']
        - (1.0 + d_env) * comp['env_basis']
        - ((1.0 + d_pcal) * comp['power_basis'] + p['P_house'])
        + comp['dstore']
    )


def auc_positive(pos, neg):
    """Empirical AUC P(score_pos > score_neg), with half credit for ties."""
    pos = np.asarray(pos); neg = np.asarray(neg)
    # N is deliberately modest, so direct comparison is transparent and stable.
    gt = (pos[:, None] > neg[None, :]).mean()
    eq = (pos[:, None] == neg[None, :]).mean()
    return float(gt + 0.5 * eq)


def tpr_at_fpr(pos, neg, fpr=0.05):
    thr = float(np.quantile(neg, 1.0 - fpr))
    return float(np.mean(np.asarray(pos) > thr)), thr


def load_flat_deterministic(t, p, rng):
    """Deterministic flat reference load for numerical-integration convergence."""
    return np.full(np.shape(t), p['P_avg'], dtype=float)


def load_phase_deterministic(t, p, rng):
    """Deterministic two-level phase-shaped load with exact analytical orbit-average P_avg."""
    hi = p['P_design']
    lo = (p['P_avg'] - p['sunlit_frac'] * hi) / (1.0 - p['sunlit_frac'])
    if lo < 0:
        raise ValueError('deterministic phase-shaped convergence profile is infeasible')
    return np.where(in_hot_phase(t, p), hi, lo)


R = {
    'version': '0.4.4',
    'environment': {
        'python': platform.python_version(),
        'numpy': np.__version__,
        'platform': platform.platform(),
    },
    'method_notes': {
        'model_status': 'project-generated parametric model; not a digital twin',
        'project_scales': 'P0-P2 and E0-E4 are project-defined, not SPARTA/NASA/NIST scales',
        'uncertainty_status': 'illustrative project assumptions, not measured operational error distributions',
    }
}

print('='*78); print('TSM-01 v0.4.4 AUTHORITATIVE CAMPAIGN'); print('='*78)

# ---------------------------------------------------------------- F-01 baseline
s_nom, s_att, st_nom, st_att, energy_delta = run_pair(P)
R['baseline'] = {
    'nominal': st_nom, 'phase_locked': st_att,
    'peak_delta_K': round(st_att['peak_C'] - st_nom['peak_C'], 4),
    'orbit_avg_energy_delta_pct': round(energy_delta, 4),
}
print('\nF-01 baseline:', R['baseline'])

# Sensitivity design. The release contains twelve entries total:
# ten true single-factor cases, one joint radiator-area/emissivity case, and
# one baseline reference. The overall range is descriptive, not a design bound.
sweeps = [
    {'case':'A=80 m2, eps=0.75', 'update':{'A_rad':80.0,'eps':0.75}, 'case_type':'joint', 'parameter_group':'radiator'},
    {'case':'A=100 m2, eps=0.85', 'update':{'A_rad':100.0,'eps':0.85}, 'case_type':'baseline_reference', 'parameter_group':'radiator'},
    {'case':'A=130 m2, eps=0.85', 'update':{'A_rad':130.0}, 'case_type':'single_factor', 'parameter_group':'radiator'},
    {'case':'C_node x0.5', 'update':{'C_node':1.8e5}, 'case_type':'single_factor', 'parameter_group':'capacitance'},
    {'case':'C_node x2', 'update':{'C_node':7.2e5}, 'case_type':'single_factor', 'parameter_group':'capacitance'},
    {'case':'UA=1500 W/K', 'update':{'UA_loop':1500.0}, 'case_type':'single_factor', 'parameter_group':'conductance'},
    {'case':'UA=6000 W/K', 'update':{'UA_loop':6000.0}, 'case_type':'single_factor', 'parameter_group':'conductance'},
    {'case':'orbit 60 min', 'update':{'period':3600.0}, 'case_type':'single_factor', 'parameter_group':'orbit_period'},
    {'case':'orbit 120 min', 'update':{'period':7200.0}, 'case_type':'single_factor', 'parameter_group':'orbit_period'},
    {'case':'P_design=36 kW', 'update':{'P_design':36000.0}, 'case_type':'single_factor', 'parameter_group':'power'},
    {'case':'P_design=45 kW', 'update':{'P_design':45000.0}, 'case_type':'single_factor', 'parameter_group':'power'},
    {'case':'P_avg=34 kW', 'update':{'P_avg':34000.0}, 'case_type':'single_factor', 'parameter_group':'power'},
]
margin=[]
for item in sweeps:
    name=item['case']; kw=item['update']
    p2=dict(P); p2.update(kw)
    if not phase_lock_is_feasible(p2):
        margin.append({'case':name,'status':'infeasible quota-neutral construction',
                       'case_type':item['case_type'],'parameter_group':item['parameter_group']})
        continue
    _, _, ns, ats, ed = run_pair(p2)
    margin.append({
        'case': name,
        'consumed_K': round(ats['peak_C'] - ns['peak_C'], 2),
        'nominal_peak_C': round(ns['peak_C'], 2),
        'attack_peak_C': round(ats['peak_C'], 2),
        'orbit_avg_energy_delta_pct': round(ed, 4),
        'case_type': item['case_type'],
        'parameter_group': item['parameter_group'],
    })
R['sensitivity_cases'] = margin
# Backward-compatible alias for plotting/consumers; v0.4.4 documentation uses sensitivity_cases.
R['margin_sweep'] = margin
vals=[x['consumed_K'] for x in margin if 'consumed_K' in x]
counts={k:sum(1 for x in margin if x.get('case_type')==k) for k in ['single_factor','joint','baseline_reference']}
# Group spans intentionally include the baseline reference so each local parameter slice is measured around the baseline.
groups={}
for g in ['radiator','capacitance','conductance','orbit_period','power']:
    gv=[x['consumed_K'] for x in margin if x.get('parameter_group')==g or (x.get('case_type')=='baseline_reference' and g!='radiator')]
    # For non-radiator groups, explicitly include the baseline once.
    if g!='radiator':
        base=next(x['consumed_K'] for x in margin if x.get('case_type')=='baseline_reference')
        gv=[base]+[x['consumed_K'] for x in margin if x.get('parameter_group')==g]
    groups[g]={'min_K':round(min(gv),2),'max_K':round(max(gv),2),'span_K':round(max(gv)-min(gv),2)}
R['sensitivity_summary']={
    'n_entries':len(vals),
    'case_counts':counts,
    'observed_range_K':{'min':min(vals),'max':max(vals),'span':round(max(vals)-min(vals),2)},
    'parameter_group_spans_K':groups,
    'range_driver':'the observed minimum and maximum are both power-related cases (P_avg=34 kW and P_design=45 kW)',
    'interpretation':'ten single-factor cases plus one joint radiator-area/emissivity case and one baseline reference; group spans are local tested slices, not global uncertainty bounds',
}
R['margin_observed_range_K']={'min':min(vals),'max':max(vals),'n_entries':len(vals),
    'scope':'observed range across 12 sensitivity entries (10 single-factor + 1 joint + 1 baseline reference); not a bound on plausible systems'}
print('F-01 sensitivity summary:', R['sensitivity_summary'])

# ---------------------------------------------------------------- F-02 matched constructions
specs={
    'radiator emissivity': ('eps_scale',0.55,1.0),
    'loop / pump': ('ua_scale',0.35,1.0),
    'environmental flux': ('q_scale',1.0,3.0),
}
synthetic={}
for name,(key,lo,hi) in specs.items():
    val, sim, st=match_fault(st_att['peak_C'],key,lo,hi)
    m=s_att['t'] >= warmup_for(P)
    rmse=float(np.sqrt(np.mean((sim['Tn'][m]-s_att['Tn'][m])**2)))
    synthetic[name]={'parameter':key,'scale':round(val,5),'peak_C':round(st['peak_C'],4),
                     'mean_C':round(st['mean_C'],4),'trajectory_rmse_K':round(rmse,3)}
    synthetic[name]['_sim']=sim
R['synthetic_peak_matched']={k:{kk:vv for kk,vv in v.items() if kk!='_sim'} for k,v in synthetic.items()}
R['peak_match_max_error_K']=round(max(abs(v['peak_C']-st_att['peak_C']) for v in R['synthetic_peak_matched'].values()),5)

# ---------------------------------------------------------------- F-03 raw candidate metrics
ua0=apparent_conductance(s_nom,P)
ref=float(energy_balance_residual(s_nom,P)[0].mean())
metric_rows=[]
case_sims=[('nominal',s_nom),('induced phase-locked load',s_att)] + [(k,v['_sim']) for k,v in synthetic.items()]
for name,s in case_sims:
    a=float(energy_balance_residual(s,P)[0].mean())
    c=float(apparent_conductance(s,P)/ua0)
    rho=float(phase_correlation(s,P))
    metric_rows.append({'case':name,'energy_residual_W':round(a,1),
                        'apparent_conductance_ratio':round(c,3),'phase_rho':round(rho,3),
                        'A_material_shift_project_threshold':bool(abs(a-ref)>200.0),
                        'C_material_shift_project_threshold':bool(abs(c-1.0)>0.05)})
R['candidate_metric_matrix']=metric_rows
R['screening_thresholds_project_selected']={'energy_residual_W':200.0,'conductance_ratio_delta':0.05,
    'status':'screening aids only; not calibrated detector thresholds'}

# S-02B: Detector-A-only telemetry-bias variant. These are comparator-specific
# values, not universal evasion thresholds.
base_induced=float(energy_balance_residual(s_att,P,power_bias=1.0)[0].mean())
bias_variant={}
metric_by_name={x['case']:x for x in metric_rows}
for fname in specs:
    target=metric_by_name[fname]['energy_residual_W']
    # If honest induced telemetry already matches this residual, no bias is needed.
    if abs(base_induced-target) <= 1.0:
        b=1.0
    else:
        lo,hi=0.5,1.0
        for _ in range(24):
            mid=0.5*(lo+hi)
            r=float(energy_balance_residual(s_att,P,power_bias=mid)[0].mean())
            # Lower reported power raises the residual.
            if r < target: hi=mid
            else: lo=mid
        b=0.5*(lo+hi)
    bias_variant[fname]={'reported_power_fraction':round(b,4),
                         'under_report_pct':round(100.0*(1.0-b),2),
                         'target_residual_W':target}
R['telemetry_bias_variant']=bias_variant

# ---------------------------------------------------------------- F-04 illustrative uncertainty
N=400
z_rng=np.random.default_rng(7001)
z_rad=z_rng.normal(size=N); z_pcal=z_rng.normal(size=N); z_env=z_rng.normal(size=N)
# Same measurement random-number design for every case; parameter z draws are also common.
components={name:prepare_residual_components(s,P,N,seed=9001) for name,s in case_sims}
base_dists={}
for name,_ in case_sims:
    base_dists[name]=residual_distribution(components[name],P,0.07*z_rad,0.03*z_pcal,0.15*z_env)

ind=base_dists['induced phase-locked load']
unc={'n':N,'sigma_radiative_coefficient':0.07,'sigma_power_calibration':0.03,
     'sigma_environment_model':0.15,'sensor_noise_sigma_K':0.3,
     'distributions':'Gaussian standard deviations; illustrative project assumptions',
     'pairs':{}}
for fname in specs:
    f=base_dists[fname]
    pooled=np.sqrt(0.5*(np.var(f,ddof=1)+np.var(ind,ddof=1)))
    d=abs(float(f.mean()-ind.mean()))/pooled if pooled else 0.0
    auc=auc_positive(f,ind)
    tpr,thr=tpr_at_fpr(f,ind,0.05)
    unc['pairs'][fname]={'standardised_mean_difference_pooled_sd':round(d,3),
                        'empirical_auc_fault_gt_induced':round(auc,3),
                        'tpr_at_5pct_induced_false_positive':round(tpr,3),
                        'threshold_W_for_5pct_fpr':round(thr,1)}
R['illustrative_uncertainty']=unc

# Clean calibration sensitivity: same standard-normal draws, same measurement-noise
# realisations, all relevant distributions recomputed at every radiative sigma.
cal={}
for tol in [0.07,0.05,0.03,0.02,0.01,0.005]:
    dn=residual_distribution(components['nominal'],P,tol*z_rad,0.03*z_pcal,0.15*z_env)
    di=residual_distribution(components['induced phase-locked load'],P,tol*z_rad,0.03*z_pcal,0.15*z_env)
    de=residual_distribution(components['radiator emissivity'],P,tol*z_rad,0.03*z_pcal,0.15*z_env)
    pooled=np.sqrt(0.5*(np.var(de,ddof=1)+np.var(di,ddof=1)))
    d=abs(float(de.mean()-di.mean()))/pooled if pooled else 0.0
    auc=auc_positive(de,di); tpr,thr=tpr_at_fpr(de,di,0.05)
    cal[f'{100*tol:g}']={
        'standardised_mean_difference_pooled_sd':round(d,3),
        'auc':round(auc,3),
        'tpr_at_5pct_fpr':round(tpr,3),
        'nominal_sd_W':round(float(dn.std(ddof=1)),1),
        'induced_sd_W':round(float(di.std(ddof=1)),1),
        'fault_sd_W':round(float(de.std(ddof=1)),1),
        'threshold_W_for_5pct_fpr':round(thr,1),
    }
R['radiative_calibration_sensitivity']=cal

# ---------------------------------------------------------------- F-05 temporal feature
blend=make_blend(P,n_orbits=N_ORBITS)
depth=[]
for d in [0.0,0.1,0.25,0.5,0.75,1.0]:
    s=simulate(blend(d),P,duration=duration_for(P,N_ORBITS),seed=5)
    st=peak_stats(s,P)
    depth.append({'depth':d,'rho':round(phase_correlation(s,P),3),
                  'peak_C':round(st['peak_C'],2),'avg_kW':round(st['orbit_avg_kW'],3)})
# Match benign schedule to the exact post-warmup average of the baseline nominal trace.
target_mean=st_nom['orbit_avg_kW']*1000.0
ben_fn=make_energy_matched_solar_profile(P,target_mean=target_mean,n_orbits=N_ORBITS)
s_ben=simulate(ben_fn,P,duration=duration_for(P,N_ORBITS),seed=21)
st_b=peak_stats(s_ben,P); rho_b=phase_correlation(s_ben,P)
near=min(depth[1:],key=lambda x:abs(x['rho']-rho_b))
benign_excursion = st_b['peak_C'] - st_nom['peak_C']
full_phase_excursion = st_att['peak_C'] - st_nom['peak_C']
R['temporal_feature']={
    'depth_sweep':depth,
    'benign_power_aware':{'rho':round(rho_b,3),'peak_C':round(st_b['peak_C'],2),
                           'avg_kW':round(st_b['orbit_avg_kW'],3),
                           'peak_excursion_vs_diversified_K':round(benign_excursion,3),
                           'fraction_of_full_phase_excursion_pct':round(100.0*benign_excursion/full_phase_excursion,1)},
    'full_phase_excursion_vs_diversified_K':round(full_phase_excursion,3),
    'nearest_attack_by_rho':near,
    'highest_partial_depth_peak_C':round(max(x['peak_C'] for x in depth if x['depth']<1.0),2),
    'conclusion':'phase correlation alone orders shaping but does not establish malicious intent; the thermal timing mechanism is not intrinsically adversarial',
    'security_interpretation':'the non-malicious synthetic power-aware schedule reproduces most of the full phase-shaped thermal excursion, so adversarial timing is one possible exploitation of an underlying resource-safety coupling',
    'residual_circularity':'attack construction and statistic share the hot-phase indicator; benign generator is independent',
}

# ---------------------------------------------------------------- F-06 model protection reference case
pm=dict(P); pm.update(A_rad=80.0,eps=0.75)
_, base, nm, am, ed=run_pair(pm)
windows=threshold_excursion_windows(base,pm)
local_slope=local_rise_rate(base,pm,window_s=60.0)
latencies=[10,300,900,1400,1500,2400]
lat={}
fn_pm_n, fn_pm_a, _ = make_energy_matched_pair(pm, BASE_SEED_N, BASE_SEED_A, N_ORBITS, 1.0)
for L in latencies:
    s=simulate(fn_pm_a,pm,duration=duration_for(pm,N_ORBITS),seed=BASE_SEED_A,
               throttle=True,throttle_latency=L)
    st=peak_stats(s,pm)
    lat[str(L)]={'peak_C':round(st['peak_C'],2),'model_hazard_reached':st['hit_model_hazard']}
R['protection_reference_case']={
    'parameters':{'A_rad_m2':80.0,'eps':0.75,'T_throttle_C':75.0,'T_model_hazard_C':90.0,
                  'shed_fraction':pm['shed_fraction'],'hysteresis_K':pm['throttle_hysteresis_K'],
                  'additional_sensor_delay_s':0.0,'actuator_transition':'idealised immediate after stated control latency',
                  'temperature_sensor':'trusted/unbiased in this experiment'},
    'unprotected_nominal_peak_C':round(nm['peak_C'],2),
    'unprotected_phase_locked_peak_C':round(am['peak_C'],2),
    'orbit_avg_energy_delta_pct':round(ed,4),
    'excursion_windows_s':windows,
    'window_min_s':round(min(windows),1) if windows else None,
    'window_mean_s':round(float(np.mean(windows)),1) if windows else None,
    'window_median_s':round(float(np.median(windows)),1) if windows else None,
    'window_max_s':round(max(windows),1) if windows else None,
    'local_60s_rise_rate_K_per_min':round(local_slope*60.0,3) if local_slope is not None else None,
    'full_15K_rise_rate_using_mean_window_K_per_min':round(15.0/(np.mean(windows)/60.0),3) if windows else None,
    'latency_sweep':lat,
    'scope':'reference-model protection behaviour only; thresholds are not generic hardware limits',
}

# ---------------------------------------------------------------- numerical integration checks
# A) Release-step/realisation sensitivity for the stochastic headline experiment.
# Changing dt changes both the Euler step and the number/timing of random samples;
# this is not a convergence series and is retained only as a mixed sensitivity check.
mixed=[]
for dt in [0.25,0.5,1.0,2.0,5.0,10.0]:
    sn, sa, n, a, _ = run_pair(P, dt=dt)
    mixed.append({'dt_s':dt,'peak_delta_K':round(a['peak_C']-n['peak_C'],4),
                  'nominal_peak_C':round(n['peak_C'],4),'phase_locked_peak_C':round(a['peak_C'],4)})
R['release_step_realisation_sensitivity']=mixed

# B) Deterministic convergence check. The forcing is fixed analytically: a flat
# P_avg reference and an exact two-level, orbit-average-matched phase profile.
# All tested dt values align with the hot/cold boundary. A 0.0625 s run is used
# as a numerical reference, and no stochastic load samples are involved.
ref_dt=0.0625
conv_dts=[0.125,0.25,0.5,1.0,2.0,4.0,8.0]

def deterministic_delta(dt):
    dur=duration_for(P,N_ORBITS)
    sn=simulate(load_flat_deterministic,P,duration=dur,dt=dt,seed=0)
    sa=simulate(load_phase_deterministic,P,duration=dur,dt=dt,seed=0)
    n=peak_stats(sn,P); a=peak_stats(sa,P)
    return a['peak_C']-n['peak_C'], n['peak_C'], a['peak_C'], a['orbit_avg_kW']-n['orbit_avg_kW']

ref_delta,ref_np,ref_ap,ref_energy=deterministic_delta(ref_dt)
conv=[]
prev_error=None
for dt in conv_dts:
    d,npk,apk,ed=deterministic_delta(dt)
    err=abs(d-ref_delta)
    order=None
    # When dt doubles, compare error ratio with the immediately finer prior dt.
    if prev_error is not None and prev_error>0 and err>0:
        order=float(np.log(err/prev_error)/np.log(2.0))
    conv.append({'dt_s':dt,'peak_delta_K':round(d,6),'abs_error_vs_ref_K':round(err,7),
                 'estimated_order_vs_finer':round(order,3) if order is not None else None,
                 'nominal_peak_C':round(npk,6),'phase_locked_peak_C':round(apk,6),
                 'avg_power_difference_kW':round(ed,9)})
    prev_error=err
R['deterministic_integration_convergence']={
    'reference_dt_s':ref_dt,
    'reference_peak_delta_K':round(ref_delta,7),
    'forcing':'deterministic flat P_avg vs deterministic two-level phase-shaped load with exact analytical orbit-average P_avg; no workload noise',
    'rows':conv,
    'interpretation':'errors decrease toward the 0.0625 s reference; the 0.5-2 s region is approximately first-order, consistent with Forward Euler for this fixed forcing experiment',
}

with open('results_v044.json','w',encoding='utf-8') as f:
    json.dump(R,f,indent=2,ensure_ascii=False)
print('\nSaved results_v044.json')
