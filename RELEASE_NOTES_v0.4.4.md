# OCTM / TSM-01 v0.4.4 Release Notes

Release date: 8 August 2026

## Release objective

v0.4.4 is a **framing, sensitivity-accounting, numerical-validation and QA-provenance** release. It does not expand the claim to a deployed system. Instead it makes the strongest current evidence explicit: in TSM-01, temporal workload placement is a thermal-safety variable, and the modelled coupling is not intrinsically adversarial.

## Priority-ordered corrections implemented

1. **F-01 reframed as a thermal-safety/resource-control finding.** Equal sampled cumulative compute energy does not bound peak thermal state in TSM-01. Adversarial timing is treated as one possible exploitation of that underlying coupling, not as the existence proof for the coupling itself.
2. **Non-malicious comparator elevated into the main interpretation.** The independently generated, energy-matched synthetic power-aware schedule reaches a 12.981 K excursion versus 15.461 K for the full phase-shaped case - **84.0%** of the modelled effect. This is synthetic evidence, not an empirical workload claim.
3. **Sensitivity accounting corrected.** The 12 entries are now explicitly classified as **10 single-factor + 1 joint radiator-area/emissivity + 1 baseline reference**. The previous “twelve one-factor-at-a-time cases” wording is removed.
4. **Sensitivity range decomposed by parameter class.** Local observed spans are radiator slice 2.63 K, node capacitance 3.01 K, loop conductance 3.59 K, orbit period 3.22 K, and power-related assumptions 15.65 K. The overall 8.03-23.68 K range is therefore reported as power-assumption-dominated rather than as a generic thermal-design spread.
5. **True deterministic numerical-convergence experiment added.** Fixed noise-free forcing is used so timestep changes do not also change workload realisation. A 0.0625 s run is the reference; error decreases toward that reference and the 0.5-2 s regime is approximately first-order, consistent with Forward Euler in this experiment.
6. **Old timestep table reclassified.** The stochastic headline experiment's 0.25-10 s table is retained only as release-step/realisation sensitivity; it is no longer called convergence.
7. **QA provenance made explicit.** The QA report identifies the review as AI-assisted, names the model/tooling role, and states that no independent human or spacecraft-thermal validation has occurred.
8. **Distribution integrity strengthened.** The complete manifested ZIP is defined as the authoritative review object; README instructs reviewers to verify `MANIFEST.sha256` before running the numerical pipeline.
9. **Independent radiator-sizing corroboration clarified.** Turyshev's 2026 representative 1 MW case uses 2,500 m2 of radiator area - 2.5 m2/kW, numerically matching TSM-01's 100 m2 / 40 kW ratio. This is explicitly limited to order-of-magnitude sizing corroboration and does not validate TSM-01 dynamics or exact parameters.
10. **Benign scheduling context expanded.** Independent data-centre literature is cited only to establish that thermal-aware workload distribution is a legitimate non-malicious scheduling class; no terrestrial result is transferred as evidence of orbital prevalence.

## Authoritative v0.4.4 numerical results

- Baseline energy-matched peak-temperature difference: **15.4609 K**.
- Sampled post-warmup average-compute-power mismatch: **-0.0002%**.
- Sensitivity entries: **12 total = 10 single-factor + 1 joint + 1 baseline reference**.
- Overall observed sensitivity range: **8.03-23.68 K**, with both extremes power-related.
- Parameter-class observed spans: radiator **2.63 K**; node capacitance **3.01 K**; loop conductance **3.59 K**; orbit period **3.22 K**; power assumptions **15.65 K**.
- Synthetic power-aware benign comparator: **12.981 K excursion**, **84.0%** of the full phase-shaped excursion; rho = **0.918**.
- Full phase-shaped excursion: **15.461 K**; rho = **1.000**.
- Deterministic Forward-Euler reference experiment: at dt=1 s, peak-delta error versus the 0.0625 s reference is approximately **0.00176 K** for the fixed-forcing experiment.
- F-02-F-06 numerical values otherwise remain as in v0.4.3 unless explicitly restated in the document.

## Remaining highest-priority uncertainties

1. Independent spacecraft-thermal review of the two-node model form and Appendix A assumptions.
2. Hardware-specific calibration of thermal capacitances, loop conductance, environmental forcing and device protection thresholds.
3. Representative workload traces for benign/adversarial temporal-shaping analysis.
4. Multi-node/shared-loop/resource-placement extension.
5. Communications SME consultation offered by Edd Salkield; technical findings remain pending.

## Release boundary

The release is a vendor-independent research baseline. It contains no claim that a named company or deployed system has a vulnerability. Independent sources are used to constrain physics and provide context; they do not convert TSM-01 into a validated spacecraft design model.
