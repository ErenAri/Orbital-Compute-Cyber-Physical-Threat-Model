# RSIM-001 — Representative Orbital Compute System Simulation

RSIM-001 is a non-authoritative representative architecture challenge. It asks whether the workload-timing-to-thermal-state coupling observed in canonical WRB-001 survives a transparent analytic LEO environment, a first-order solar/battery bus, requested-versus-executed accounting, and a canonical-derived monotone thermal limiter. It does not validate an attack, vulnerability, spacecraft, flight thermal design, vendor architecture, or orbital data center.

## Frozen architecture and causal order

The canonical v0.4.4 two-node thermal plant and Forward-Euler equations are unchanged. Each one-second interval reads the left-endpoint thermal, battery, and FDIR states; evaluates environment and the frozen requested WRB workload; computes electrical feasibility; applies the monotone FDIR limit; executes the minimum allowed compute power; then advances the frozen thermal kernel and battery state.

The modes are `THERMAL_ONLY`, `POWER_CONSTRAINED`, and `CLOSED_LOOP`. W0–W5 are generated once per seed using the existing WRB canonical timebase, hot mask, energy matching, RNG lineage, and W4 power-availability input. The same requested array is replayed across both environments and all modes. W5 remains the phase-shaped adversarial candidate and is not retargeted to E1.

## Environments

E0 is the canonical v0.4.4 150/40 W/m² square wave. E1 uses the frozen analytic cylindrical-shadow and component equations in `src/octm/rsim/environment.py`: absorbed direct solar, an analytic albedo approximation, and Earth IR. Solar-array incidence is separate from radiator solar incidence. Visible absorptivity is separate from IR absorptivity; the latter equals canonical emissivity only under the declared grey-body/Kirchhoff assumption. E1 coefficients are not tuned to E0.

The E1 smoke run is a **fixed-wall-clock representative environment challenge**. The 43,200-second horizon preserves the WRB traces and canonical `[10,800, 43,200)` measurement mask. It spans 7.527453229594017 E1 periods, not an integer warmup-plus-measurement orbit count. No E1 periodicity, convergence, or steady-state claim is permitted.

## Electrical balance

A0 supports the representative 32 kW nominal bus load in both E0 and E1. The selected sunlit bus power is 53,731.74872665535 W and capacity is 102,818,124.44650389 J (28.56059012402886 kWh). Both are `DERIVED_REPRESENTATIVE`, not flight sizing, and neither is selected to make W5 feasible.

Charging stores `eta_charge * P_charge_bus * dt`; discharging removes `P_discharge_bus * dt / eta_discharge`. Housekeeping has priority. Compute is denied before the battery crosses its minimum energy. Surplus is recorded as curtailment and any unsupplied housekeeping transitions the run to `SYSTEM_POWER_DEFICIT`.

The cumulative balance is checked as:

`solar energy + initial stored energy - final stored energy = served bus load + charge loss + discharge loss + curtailment`.

The float64 closure tolerance is `max(1e-4 J, 1e-12 × total processed solar-plus-battery-withdrawal energy)`. Both the maximum absolute cumulative residual and the applicable tolerance are serialized.

## FDIR

The controller is named **RSIM canonical-derived monotone FDIR**. It preserves canonical 348.15 K arming, 5 K hysteresis, configurable latency, and 12 kW shedding-limit semantics, but applies 12 kW as a limit rather than an absolute replacement command:

`P_executed = min(P_requested, P_power_feasible, P_fdir_limit, P_design)`.

For requests at or above 12 kW it is regression-tested against canonical activation, shedding, thermal trajectory, and recovery. Below 12 kW it intentionally differs: canonical may replace a lower request with 12 kW, while RSIM never increases requested compute.

## Smoke protocol and interpretation

Seeds 0–9, W0–W5, E0/E1, and three modes produce at most 360 runs. The campaign is for harness and invariant checking only and receives no `ROBUST`, `SAFE`, `VULNERABLE`, attack-success, or attack-failure classification. Any temperature reduction in constrained modes must be reported beside executed energy and denied fraction.

Hard stops include canonical provenance drift, E0 Mode-A WRB disagreement, thermal-bridge error above 1e-10 K, projected CLOSED_LOOP bridge time above 600 seconds, power/energy/SOC invariant failure, nonfinite state, hidden clipping, or FDIR increasing compute power.
