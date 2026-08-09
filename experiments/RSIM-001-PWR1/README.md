# RSIM-001-PWR1 — Reserve-Aware Essential-Load Admission Challenge

RSIM-001-PWR1 changes one architectural dimension relative to the frozen RSIM-001 smoke: compute admission protects enough internal battery energy to serve the 2 kW mandatory housekeeping load through the remaining deterministic no-generation interval. The A0 hardware, E0/E1 environments, W0–W5 traces, thermal plant, FDIR, and wall-clock measurement window are unchanged.

The frozen smoke architecture is labelled A0-M (myopic admission). Its existing artifacts under `results/RSIM-001-smoke/` are read as immutable comparison inputs and are not regenerated or reinterpreted. The new architecture is A0-R (reserve-aware essential-load admission).

For time-to-next-generation `t_next`, the controller protects

`E_protected = SOC_min × E_capacity + P_house × t_next / eta_discharge`.

Housekeeping may consume its scheduled share of this reserve. Compute may use instantaneous solar remaining after housekeeping and stored battery energy strictly above the protected level. No energy is reserved for future compute, W5, FDIR, throughput, or any workload identity.

Compute denial is attributed through a fixed additive waterfall: instantaneous hardware feasibility, then battery-reserve protection, then FDIR. Reserve-induced denial is normal valid operation. Only mandatory-housekeeping loss emits `SYSTEM_POWER_DEFICIT`.

This is a non-authoritative representative controller challenge. It does not validate an attack, vulnerability, spacecraft, power subsystem, thermal design, or deployed orbital-compute architecture. It assigns no SAFE, VULNERABLE, or attack-success classification.
