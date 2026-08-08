"""
TSM-01: vendor-independent parametric thermal/power reference model.

Purpose
-------
Test whether time-shaping an authorised compute workload can alter peak thermal
state at nearly equal orbit-integrated compute energy, and explore candidate
observability/protection mechanisms.

Model
-----
Two lumped thermal nodes:
    compute/coldplate node <-- UA_loop --> radiator --> radiative heat rejection

Epistemic status
----------------
This is a project-generated parametric model, not a digital twin and not a
validated spacecraft design model. Parameters are explicit project assumptions
unless a source is listed in the accompanying documentation. No company sizing
claim is used as a normative model input.
"""
from __future__ import annotations
import numpy as np
from numba import njit

# 2019 SI exact value; NIST/CODATA.
SIGMA = 5.670374419e-8  # Stefan-Boltzmann constant [W m^-2 K^-4]

@njit(cache=True)
def _integrate_kernel(commanded, q_arr, dt, C_node, C_rad, UA, eps, A_rad, T_space,
                      P_house, Tn0, Tr0, throttle, T_throttle, latency,
                      shed_power, hysteresis):
    n = commanded.size
    Tn = np.zeros(n); Tr = np.zeros(n); Pc = np.zeros(n)
    Tn[0] = Tn0; Tr[0] = Tr0
    armed_at = -1.0
    shedding = False
    for i in range(n - 1):
        Pw = commanded[i]
        if throttle:
            if Tn[i] >= T_throttle:
                if armed_at < 0.0:
                    armed_at = i * dt
                if (not shedding) and ((i * dt) - armed_at >= latency):
                    shedding = True
            elif Tn[i] < T_throttle - hysteresis:
                shedding = False
                armed_at = -1.0
            if shedding:
                Pw = shed_power
        Pc[i] = Pw
        Q_loop = UA * (Tn[i] - Tr[i])
        Q_rad = eps * SIGMA * A_rad * (Tr[i] ** 4 - T_space ** 4) - q_arr[i] * A_rad
        Tn[i + 1] = Tn[i] + dt * ((Pw + P_house - Q_loop) / C_node)
        Tr[i + 1] = Tr[i] + dt * ((Q_loop - Q_rad) / C_rad)
    Pc[-1] = Pc[-2]
    return Tn, Tr, Pc

P = dict(
    A_rad=100.0,                # m^2, assumed effective radiating area
    eps=0.85,                   # assumed effective IR emissivity
    C_node=3.6e5,               # J/K, assumed node+coldplate+coolant capacitance
    C_rad=2.25e5,               # J/K, assumed radiator capacitance
    UA_loop=3000.0,             # W/K, assumed effective node-radiator conductance
    P_house=2000.0,             # W, assumed platform/housekeeping heat at this node
    P_design=40000.0,           # W, assumed compute design-point heat load
    P_avg=30000.0,              # W, assumed diversified average compute load
    T_space=3.0,                # K, idealised deep-space radiative sink
    q_hot=150.0,                # W/m^2, assumed lumped absorbed hot-phase flux
    q_cold=40.0,                # W/m^2, assumed lumped absorbed cold-phase flux
    T_throttle=348.15,          # K (75 C), PROJECT-ASSUMED protection threshold
    T_model_hazard=363.15,      # K (90 C), PROJECT-ASSUMED upper model limit
    shed_fraction=0.30,         # fraction of P_design retained while shedding
    throttle_hysteresis_K=5.0,  # K
    period=5400.0,              # s, representative ~90 min LEO period
    sunlit_frac=0.62,           # project-assumed hot/sunlit fraction
    Tn0=320.0,                  # K, initial compute-node state (washed out by warmup)
    Tr0=305.0,                  # K, initial radiator state (washed out by warmup)
)


def duration_for(p: dict, n_orbits: float = 8.0) -> float:
    return float(n_orbits * p['period'])


def warmup_for(p: dict, warmup_orbits: float = 2.0) -> float:
    return float(warmup_orbits * p['period'])


def env_flux(t, p):
    """Idealised absorbed environmental heat flux [W/m^2]."""
    phase = (np.asarray(t) % p['period']) / p['period']
    return np.where(phase < p['sunlit_frac'], p['q_hot'], p['q_cold'])


def in_hot_phase(t, p):
    return ((np.asarray(t) % p['period']) / p['period']) < p['sunlit_frac']


# ---------------------------------------------------------------- load profiles

def load_nominal(t, p, rng):
    """Synthetic diversified load; not an empirical workload trace."""
    slow = 0.12 * p['P_avg'] * np.sin(2 * np.pi * t / 1730.0 + 0.7)
    return np.clip(
        p['P_avg'] + slow + rng.normal(0, 0.03 * p['P_avg'], size=np.shape(t)),
        0.35 * p['P_design'],
        p['P_design'],
    )


def _eclipse_level(p, hi=None):
    """Cold-phase power giving exactly P_avg for the ideal two-level profile."""
    hi = p['P_design'] if hi is None else hi
    return (p['P_avg'] - p['sunlit_frac'] * hi) / (1.0 - p['sunlit_frac'])


def phase_lock_is_feasible(p, hi=None):
    return _eclipse_level(p, hi) >= 0.0


def load_phase_locked(t, p, rng, depth=1.0):
    """Synthetic adversarial profile at approximately constant orbit-average energy.

    `depth=0` uses a flat P_avg ideal profile; `depth=1` places P_design in the
    hot phase and compensates in the cold phase. A feasibility guard prevents a
    negative cold-phase level from being silently clipped.
    """
    if not 0.0 <= depth <= 1.0:
        raise ValueError('depth must be in [0,1]')
    hi = p['P_avg'] + depth * (p['P_design'] - p['P_avg'])
    lo = _eclipse_level(p, hi)
    if lo < -1e-9:
        raise ValueError(
            f"quota-neutral phase-lock infeasible: cold-phase level {lo:.1f} W < 0; "
            f"P_avg={p['P_avg']:.1f}, hot_fraction*hi={p['sunlit_frac'] * hi:.1f}"
        )
    base = np.where(in_hot_phase(t, p), hi, lo)
    return np.clip(base + rng.normal(0, 0.01 * p['P_avg'], size=np.shape(t)), 0.0, p['P_design'])


def solar_availability(t, p):
    """Smooth synthetic power-availability proxy, independent of attack generator."""
    ph = (np.asarray(t) % p['period']) / p['period']
    x = np.clip(ph / p['sunlit_frac'], 0.0, 1.0)
    return np.where(ph < p['sunlit_frac'], np.sin(np.pi * x) ** 0.5, 0.0)


def load_solar_available(t, p, rng, gain=1.0):
    """Synthetic benign power-aware schedule from smooth availability proxy."""
    a = solar_availability(t, p)
    lo = 0.35 * p['P_design']
    raw = lo + gain * (p['P_design'] - lo) * a
    return np.clip(raw + rng.normal(0, 0.02 * p['P_avg'], size=np.shape(t)), 0.0, p['P_design'])


def _bounded_shift_to_mean(x: np.ndarray, target: float, lo: float, hi: float) -> np.ndarray:
    """Shift then clip a trace so its mean matches target (monotonic bisection)."""
    a, b = lo - float(np.max(x)), hi - float(np.min(x))
    for _ in range(80):
        m = 0.5 * (a + b)
        y = np.clip(x + m, lo, hi)
        if y.mean() < target:
            a = m
        else:
            b = m
    return np.clip(x + 0.5 * (a + b), lo, hi)




def _bounded_shift_to_subset_mean(x: np.ndarray, subset, target: float, lo: float, hi: float) -> np.ndarray:
    """Shift/clip a trace so the selected subset has the requested sampled mean."""
    x = np.asarray(x, dtype=float)
    sel = np.asarray(subset)
    a, b = lo - float(np.max(x)), hi - float(np.min(x))
    for _ in range(80):
        m = 0.5 * (a + b)
        y = np.clip(x + m, lo, hi)
        if float(y[sel].mean()) < target:
            a = m
        else:
            b = m
    return np.clip(x + 0.5 * (a + b), lo, hi)


def make_energy_matched_pair(p, seed_n=11, seed_a=12, n_orbits=8, dt=1.0):
    """Return fixed nominal and phase-shaped traces with equal post-warmup sampled mean.

    Matching is performed on the same complete-orbit post-warmup window used by
    the release metrics. This makes cumulative sampled compute energy a controlled
    variable rather than an approximate property of the analytical two-level profile.
    """
    duration = duration_for(p, n_orbits)
    n = int(round(duration / dt)); t = np.arange(n) * dt
    rn, ra = np.random.default_rng(seed_n), np.random.default_rng(seed_a)
    pn = np.asarray(load_nominal(t, p, rn), dtype=float)
    pa = np.asarray(load_phase_locked(t, p, ra), dtype=float)
    i0 = int(round(warmup_for(p) / dt))
    subset = np.arange(n) >= i0
    target = float(pn[subset].mean())
    pa = _bounded_shift_to_subset_mean(pa, subset, target, 0.0, p['P_design'])
    return trace_load(pn, dt), trace_load(pa, dt), target

def trace_load(trace: np.ndarray, dt: float = 1.0):
    trace = np.asarray(trace, dtype=float)
    n = len(trace)
    def f(t, p, rng, _tr=trace, _dt=dt, _n=n):
        a = np.asarray(t)
        idx = np.minimum((a / _dt).astype(int), _n - 1)
        out = _tr[idx]
        return float(out) if np.ndim(t) == 0 else out
    return f


def make_blend(p, seed_n=11, seed_a=12, n_orbits=8, dt=1.0):
    """Controlled interpolation between fixed nominal and phase-shaped traces.

    The same two source traces are used at all depths. A bounded shift matches
    every blended trace to the nominal trace's exact sampled mean, avoiding the
    v0.4.1 generator-switch confound.
    """
    duration = duration_for(p, n_orbits)
    n = int(round(duration / dt)); t = np.arange(n) * dt
    rn, ra = np.random.default_rng(seed_n), np.random.default_rng(seed_a)
    pn = np.asarray(load_nominal(t, p, rn), dtype=float)
    pa = np.asarray(load_phase_locked(t, p, ra), dtype=float)
    i0 = int(round(warmup_for(p) / dt))
    subset = np.arange(n) >= i0
    target = float(pn[subset].mean())
    def fn(depth):
        b = (1.0 - depth) * pn + depth * pa
        b = _bounded_shift_to_subset_mean(b, subset, target, 0.0, p['P_design'])
        return trace_load(b, dt)
    return fn


def make_energy_matched_solar_profile(p, target_mean=None, seed=21, n_orbits=8, dt=1.0):
    """Fixed benign power-aware trace, energy-matched for controlled comparison."""
    duration = duration_for(p, n_orbits)
    n = int(round(duration / dt)); t = np.arange(n) * dt
    rng = np.random.default_rng(seed)
    raw = np.asarray(load_solar_available(t, p, rng), dtype=float)
    i0 = int(round(warmup_for(p) / dt))
    subset = np.arange(n) >= i0
    target = p['P_avg'] if target_mean is None else float(target_mean)
    matched = _bounded_shift_to_subset_mean(raw, subset, target, 0.0, p['P_design'])
    return trace_load(matched, dt)


# ---------------------------------------------------------------- integrator

def simulate(load_fn, p, duration=None, dt=1.0, seed=0,
             eps_scale=1.0, ua_scale=1.0, q_scale=1.0,
             throttle=False, throttle_latency=0.0):
    """Forward-Euler integration of the two-node reference model."""
    duration = duration_for(p) if duration is None else float(duration)
    rng = np.random.default_rng(seed)
    n = int(round(duration / dt))
    t = np.arange(n) * dt
    eps = p['eps'] * eps_scale
    UA = p['UA_loop'] * ua_scale
    commanded = np.asarray(load_fn(t, p, rng), dtype=float)
    if commanded.ndim == 0:
        commanded = np.full(n, float(commanded))
    if commanded.shape[0] != n:
        raise ValueError(f'load profile returned {commanded.shape[0]} samples; expected {n}')
    q_arr = np.asarray(env_flux(t, p), dtype=float) * q_scale
    Tn, Tr, Pc = _integrate_kernel(
        commanded, q_arr, float(dt), float(p['C_node']), float(p['C_rad']),
        float(UA), float(eps), float(p['A_rad']), float(p['T_space']),
        float(p['P_house']), float(p['Tn0']), float(p['Tr0']), bool(throttle),
        float(p['T_throttle']), float(throttle_latency),
        float(p['shed_fraction'] * p['P_design']), float(p['throttle_hysteresis_K']))
    return dict(t=t, Tn=Tn, Tr=Tr, P=Pc)


# ---------------------------------------------------------------- diagnostics

def energy_balance_residual(sim, p, power_bias=1.0, sensor_noise=0.3, seed=1,
                            warmup=None):
    """Orbit-integrated energy-balance residual (Detector A candidate metric)."""
    warmup = warmup_for(p) if warmup is None else float(warmup)
    rng = np.random.default_rng(seed)
    Tr = sim['Tr'] + rng.normal(0, sensor_noise, sim['Tr'].size)
    Tn = sim['Tn'] + rng.normal(0, sensor_noise, sim['Tn'].size)
    Pm = sim['P'] * power_bias
    dt = sim['t'][1] - sim['t'][0]
    q = env_flux(sim['t'], p)
    rejected = p['eps'] * SIGMA * p['A_rad'] * (Tr ** 4 - p['T_space'] ** 4)
    absorbed = q * p['A_rad']
    supplied = Pm + p['P_house']
    n_per = int(round(p['period'] / dt))
    out = []
    i = int(round(warmup / dt))
    while i + n_per < len(Tr):
        sl = slice(i, i + n_per)
        d_store = (
            p['C_node'] * (Tn[i + n_per] - Tn[i])
            + p['C_rad'] * (Tr[i + n_per] - Tr[i])
        ) / p['period']
        out.append(float((rejected[sl] - absorbed[sl] - supplied[sl]).mean() + d_store))
        i += n_per
    return np.asarray(out), Pm


def phase_correlation(sim, p, warmup=None):
    """Candidate temporal feature: correlation of compute power with hot-phase indicator."""
    warmup = warmup_for(p) if warmup is None else float(warmup)
    m = sim['t'] >= warmup
    hot = in_hot_phase(sim['t'][m], p).astype(float)
    x = sim['P'][m] - sim['P'][m].mean()
    y = hot - hot.mean()
    denom = np.sqrt((x ** 2).sum() * (y ** 2).sum())
    return float((x * y).sum() / denom) if denom > 0 else 0.0


def apparent_conductance(sim, p, warmup=None, sensor_noise=0.3, seed=3):
    """Candidate gradient metric: orbit-mean apparent node-radiator conductance."""
    warmup = warmup_for(p) if warmup is None else float(warmup)
    rng = np.random.default_rng(seed)
    m = sim['t'] >= warmup
    Tn = sim['Tn'][m] + rng.normal(0, sensor_noise, m.sum())
    Tr = sim['Tr'][m] + rng.normal(0, sensor_noise, m.sum())
    Q = sim['P'][m] + p['P_house']
    return float(Q.mean() / (Tn - Tr).mean())


def peak_stats(sim, p, warmup=None):
    warmup = warmup_for(p) if warmup is None else float(warmup)
    m = sim['t'] >= warmup
    Tn = sim['Tn'][m]
    return dict(
        peak_C=float(Tn.max() - 273.15),
        mean_C=float(Tn.mean() - 273.15),
        hit_throttle=bool(Tn.max() >= p['T_throttle']),
        hit_model_hazard=bool(Tn.max() >= p['T_model_hazard']),
        orbit_avg_kW=float(sim['P'][m].mean() / 1000.0),
    )


def threshold_excursion_windows(sim, p, warmup=None):
    """Return per-excursion times from upward T_throttle crossing to T_model_hazard.

    Only a hazard crossing occurring before the temperature next falls below the
    throttle threshold is associated with that excursion.
    """
    warmup = warmup_for(p) if warmup is None else float(warmup)
    m = sim['t'] >= warmup
    t = sim['t'][m]; T = sim['Tn'][m]
    above = T >= p['T_throttle']
    starts = np.where(above & np.r_[True, ~above[:-1]])[0]
    out = []
    for s in starts:
        end_candidates = np.where(~above[s + 1:])[0]
        e = s + 1 + end_candidates[0] if end_candidates.size else len(T)
        h = np.where(T[s:e] >= p['T_model_hazard'])[0]
        if h.size:
            out.append(float(t[s + h[0]] - t[s]))
    return out


def local_rise_rate(sim, p, crossing='throttle', warmup=None, window_s=60.0):
    """Linear-fit temperature slope over `window_s` after first selected crossing [K/s]."""
    warmup = warmup_for(p) if warmup is None else float(warmup)
    thr = p['T_throttle'] if crossing == 'throttle' else p['T_model_hazard']
    m = sim['t'] >= warmup
    t = sim['t'][m]; T = sim['Tn'][m]
    ix = np.where(T >= thr)[0]
    if ix.size == 0:
        return None
    i = ix[0]
    j = np.searchsorted(t, t[i] + window_s)
    if j <= i + 2:
        return None
    return float(np.polyfit(t[i:j], T[i:j], 1)[0])
