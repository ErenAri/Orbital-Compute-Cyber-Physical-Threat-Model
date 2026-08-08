from __future__ import annotations

import numpy as np

from src.octm.baselines.v044 import thermal_model as canonical
from src.octm.rsim.fdir import FDIRParameters, FDIRState, fdir_decision
from src.octm.rsim.thermal_bridge import one_step


def _canonical_trace(requested: np.ndarray, flux: np.ndarray, latency: float):
    p = canonical.P
    return canonical._integrate_kernel(
        requested, flux, 1.0, p["C_node"], p["C_rad"], p["UA_loop"], p["eps"],
        p["A_rad"], p["T_space"], p["P_house"], 349.0, 330.0, True,
        p["T_throttle"], latency, p["shed_fraction"] * p["P_design"],
        p["throttle_hysteresis_K"],
    )


def test_requests_at_or_above_12kw_match_canonical_trajectory_and_recovery() -> None:
    n = 600
    requested = np.full(n, 20_000.0)
    flux = np.zeros(n)
    canonical_tn, canonical_tr, canonical_power = _canonical_trace(requested, flux, 0.0)
    tn = np.empty(n); tr = np.empty(n); executed = np.empty(n)
    tn[0], tr[0] = 349.0, 330.0
    state = FDIRState()
    activated = recovered = 0
    params = FDIRParameters(latency_s=0.0)
    for i in range(n):
        decision = fdir_decision(
            node_temperature_K=tn[i], time_s=float(i), requested_compute_W=requested[i],
            state=state, enabled=True, params=params,
        )
        state = decision.state
        activated += int(decision.activated); recovered += int(decision.recovered)
        executed[i] = min(requested[i], decision.power_limit_W)
        if i < n - 1:
            tn[i + 1], tr[i + 1] = one_step(executed[i], flux[i], tn[i], tr[i])
    assert activated >= 1
    assert recovered >= 1
    assert np.array_equal(executed[:-1], canonical_power[:-1])
    assert np.max(np.abs(tn - canonical_tn)) <= 1e-10
    assert np.max(np.abs(tr - canonical_tr)) <= 1e-10


def test_sub_12kw_request_documents_intentional_monotone_divergence() -> None:
    requested = np.array([8_000.0, 8_000.0])
    flux = np.zeros(2)
    _, _, canonical_power = _canonical_trace(requested, flux, 0.0)
    decision = fdir_decision(
        node_temperature_K=349.0, time_s=0.0, requested_compute_W=8_000.0,
        state=FDIRState(), enabled=True, params=FDIRParameters(latency_s=0.0),
    )
    rsim_power = min(8_000.0, decision.power_limit_W)
    assert canonical_power[0] == 12_000.0
    assert rsim_power == 8_000.0
    assert rsim_power <= requested[0]
