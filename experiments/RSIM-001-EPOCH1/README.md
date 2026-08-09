# RSIM-001-EPOCH1 — Relative Orbital Epoch Robustness Challenge

RSIM-001-EPOCH1 varies only the relative phase between each frozen W0–W5 requested workload trace and the unchanged representative E1 analytic LEO environment. It uses the unchanged A0-R hardware and essential-load reserve admission introduced by RSIM-001-PWR1.

The eight preregistered phase offsets are 0 through 7/8 orbit in 1/8-orbit increments. E1 orbital position, eclipse, illumination, solar generation, albedo, and radiator forcing shift together. Workload samples, RNG lineage, measurement window, thermal plant, FDIR, battery equations, reserve equations, and hardware do not shift.

For every workload and mode, delta peak temperature is paired against W0 with the same seed and epoch. The campaign reports all 80 seed×epoch observations plus per-epoch medians; it assigns no materiality threshold or ROBUST, CONDITIONAL, SAFE, VULNERABLE, or attack-success classification.

The 960-run matrix includes only POWER_CONSTRAINED and CLOSED_LOOP. The campaign executes twice before writing normative artifacts, and the serialized scientific payloads must be identical. Offset zero must exactly reproduce the frozen E1 subset of RSIM-001-PWR1.

This remains a non-authoritative sensitivity experiment. It is not a new attack, workload optimization, orbital mission design, high-fidelity propagator, or spacecraft validation.
