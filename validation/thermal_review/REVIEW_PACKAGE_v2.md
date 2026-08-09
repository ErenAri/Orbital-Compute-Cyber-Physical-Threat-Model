# OCTM Independent Spacecraft-Thermal Model Review Package v2

**Project:** Orbital Compute Cyber-Physical Threat Model (OCTM)  
**Model under review:** canonical TSM-01 v0.4.4 two-node thermal plant, plus non-authoritative RSIM-001 representative architecture challenges  
**Review requested:** independent spacecraft-thermal model-form and assumption review  
**Review status:** request package only; no independent review or endorsement is recorded here  
**Date:** 9 August 2026

---

## 1. Decision requested from the reviewer

OCTM investigates whether temporal placement of onboard compute workload can change peak thermal state even when the requested compute-energy budget is held equal over the comparison window.

The project is **not** asking the reviewer to validate a cyberattack, vulnerability, flight design, vendor architecture, orbital data center, or safety certification. The requested decision is narrower:

> **Is the TSM-01 reduced-order thermal plant physically suitable for screening workload-timing → thermal-state coupling, and which missing states, time constants, boundary conditions, parameter assumptions, or protection mechanisms could materially change, reverse, or invalidate the quantitative result?**

Please judge the model as a screening abstraction. The strongest useful review would identify the minimum thermal fidelity required for a defensible next experiment.

### Requested final disposition

Use `REVIEW_FORM_v2.md` and choose one:

- **A — Suitable for screening as currently formulated.** The two-node abstraction is acceptable for the stated question, with limitations retained.
- **B — Suitable for screening after major revisions.** The question is meaningful, but one or more model-form changes are required before quantitative interpretation.
- **C — Not suitable for quantitative screening in its current form.** Missing physics or boundary assumptions are likely to dominate, reverse, or make the reported effect uninterpretable.

A different disposition is welcome if technically more appropriate.

---

## 2. Claim boundary

### 2.1 What the current evidence supports

Within the current model assumptions, workload timing is a cyber-physical resource variable: equal requested compute-energy budgets can produce different peak thermal states when the temporal power trace interacts with a time-varying orbital thermal environment.

The evidence chain now has four layers:

1. **TSM-01 v0.4.4 baseline** — canonical two-node parametric thermal model.
2. **WRB-001** — 100 paired seeds across six workload families under the canonical environment.
3. **RSIM-001 / PWR1** — representative analytic LEO forcing, a first-order solar/battery power system, requested-versus-executed workload accounting, reserve-aware essential-load admission, and a simplified monotone thermal limiter.
4. **RSIM-001-EPOCH1** — eight relative E1 orbital epochs with the requested workload traces held fixed.

These layers improve internal falsification and architecture challenge. They do **not** establish physical validity of the thermal plant.

### 2.2 What the evidence does not support

The project does not currently claim that:

- any deployed spacecraft or named vendor has a vulnerability;
- the reported temperature excursions transfer directly to flight hardware;
- the TSM-01 parameters describe a real spacecraft design;
- E1 is a flight environment model;
- the A0 electrical architecture is flight sizing;
- W5 is a validated attack path;
- the simplified FDIR is representative flight protection;
- the project has demonstrated hardware damage or a universal safety-threshold breach;
- repository reproducibility is evidence of physical correctness.

---

## 3. Thermal plant under review

TSM-01 contains two lumped nodes:

1. **Compute / cold-plate node** — receives time-varying compute power and fixed housekeeping heat.
2. **Radiator node** — receives heat through one effective conductance, absorbs environmental heat flux, and rejects heat radiatively.

The canonical balances are:

\[
C_{node}\frac{dT_{node}}{dt}
= P_{compute} + P_{house}
- UA\,(T_{node}-T_{rad})
\]

\[
C_{rad}\frac{dT_{rad}}{dt}
= UA\,(T_{node}-T_{rad})
+ A\,q_{env}
- \epsilon\sigma A\,(T_{rad}^{4}-T_{space}^{4})
\]

The release uses Forward Euler with `dt = 1 s`.

### 3.1 Canonical baseline parameters

| Parameter | Value | Evidence status | Main review question |
|---|---:|---|---|
| Radiator area | 100 m² | Project-assumed | Is this a defensible scaling abstraction for 40 kW-class compute heat? |
| IR emissivity | 0.85 | Project-assumed | Is a single effective value adequate? |
| Compute-node heat capacity | 3.6×10⁵ J/K | Project-assumed | What hardware/coolant mass is implicitly represented? |
| Radiator heat capacity | 2.25×10⁵ J/K | Project-assumed | Does one radiator state distort transient peak response? |
| Effective conductance `UA` | 3000 W/K | Project-assumed | Can one `UA` represent cold plate, loop transport and radiator coupling? |
| Housekeeping heat | 2 kW | Project-assumed | Should bus/structure heat be a separate state? |
| Compute design power | 40 kW | Project-assumed | Power-related assumptions dominate the current local sensitivity set. |
| Diversified average compute | 30 kW | Project-assumed | No representative hardware calibration exists yet. |
| Deep-space sink | 3 K | Idealised | Acceptable if external flux is represented separately? |
| Canonical hot/cold flux | 150 / 40 W/m² | Project-assumed | Replaced only in RSIM E1 challenge, not physically validated. |
| Canonical orbit period | 5400 s | Representative | Is this timescale adequate for screening? |
| Throttle threshold | 348.15 K | Project-assumed | Not a universal hardware limit. |
| Upper model threshold | 363.15 K | Project-assumed | Not a universal damage limit. |

### 3.2 Main missing physical states

The reviewer should explicitly challenge the consequences of omitting:

- coolant inventory and transport delay;
- pump/loop capacity and nonlinear flow behaviour;
- cold-plate/package thermal resistance and capacitance;
- heat exchanger dynamics;
- radiator segmentation/manifolds/local gradients;
- multiple compute nodes and physical workload placement;
- spacecraft bus/structure coupling;
- temperature-dependent properties;
- geometry- and attitude-resolved radiator view factors;
- hardware-derived workload → electrical power → heat dynamics.

The key question is not whether a higher-fidelity model is possible, but **which omitted state could change the sign, ordering, phase relationship, or order of magnitude of the timing effect**.

---

## 4. Reproducibility and numerical controls

Current repository controls establish:

- canonical manifest: **15/15 PASS**;
- canonical scientific reproduction: **364/364 exact**, maximum numerical difference **0.0**;
- E0/RSIM regression against canonical WRB smoke subset: exact;
- repeated one-step frozen thermal-kernel bridge versus monolithic frozen kernel: **0.0 K** observed difference in the implemented regression;
- RSIM-EPOCH1 was rerun deterministically with byte-identical scientific payload;
- current tests after EPOCH1: **94 passed**.

The v0.4.4 deterministic convergence experiment reports approximately **0.00176 K** peak-delta error at `dt = 1 s` relative to a `0.0625 s` reference for the tested fixed-forcing case.

These checks bound implementation/numerical drift. They do **not** bound model-form error.

---

## 5. WRB-001: workload-family robustness inside canonical TSM-01

WRB-001 holds the sampled requested compute-energy target equal within each paired seed while changing workload temporal structure.

### 5.1 Workload families

| ID | Workload | Allowed information | Interpretation |
|---|---|---|---|
| W0 | `constant_reference` | W1 mean target | Reference |
| W1 | `diversified_stochastic` | Time + explicit RNG | Synthetic benign comparator |
| W2 | `bursty_benign` | Own RNG; no thermal/orbit input | Synthetic benign workload |
| W3 | `queue_driven_benign` | Synthetic arrivals/backlog | Synthetic benign scheduler |
| W4 | `power_aware_benign` | Time + abstract electrical availability; no thermal state | Synthetic benign comparator |
| W5 | `phase_shaped_candidate` | Canonical hot-phase convention | Adversarial candidate, not validated attack |

### 5.2 Canonical 100-seed result

Median peak-temperature excursion relative to W0:

| Workload | Median ΔT vs W0 |
|---|---:|
| W1 | **1.892 K** |
| W2 | **8.063 K** |
| W3 | **8.184 K** |
| W4 | **10.439 K** |
| W5 | **17.377 K** |

The historical v0.4.4 nominal-versus-phase-shaped single-run result was approximately **15.4609 K**. WRB-001 W5 versus W1 is approximately **15.484 K** across the paired campaign, while W5 versus the constant W0 reference is larger. Reference definition therefore matters.

Under the canonical WRB baseline, no tested workload spends time above the project-assumed 75 °C throttle threshold or 90 °C upper model threshold. WRB establishes a peak-state/margin coupling within the model, not a threshold-breach claim.

---

## 6. RSIM-001: representative architecture challenge

RSIM adds constraints around the frozen TSM-01 thermal plant without changing its thermal equations.

### 6.1 E1 representative analytic LEO environment

E1 is deliberately transparent and non-flight-validated. It uses:

- circular altitude: **550 km** (`ASSUMED_EXPLORATORY`);
- analytic period: approximately **5738.993 s**;
- beta angle: **0 rad** (`ASSUMED_EXPLORATORY`);
- direct solar irradiance: **1361 W/m²**;
- representative Earth Bond albedo: **0.294**;
- representative Earth IR: **234 W/m²**;
- radiator solar absorptivity: **0.20** (`ASSUMED_EXPLORATORY`);
- radiator direct-solar incidence factor: **0.25** (`ASSUMED_EXPLORATORY`);
- radiator Earth-view factor: **0.50** (`ASSUMED_EXPLORATORY`);
- IR absorptivity: **0.85**, tied to canonical emissivity under an explicit grey-body/Kirchhoff assumption.

The absorbed E1 radiator flux separates direct solar, analytic albedo and Earth IR. The coefficients were **not** tuned to reproduce E0.

The reviewer should treat the radiator incidence and Earth-view factors as important unvalidated assumptions, not as architecture facts.

### 6.2 A0 representative power system

A0 uses a first-order solar/battery energy-balance model:

- nominal bus load basis: **32 kW** = 30 kW compute + 2 kW housekeeping;
- sunlit solar-bus rating: **53.7317 kW** (`DERIVED_REPRESENTATIVE`);
- battery capacity: **28.5606 kWh** (`DERIVED_REPRESENTATIVE`);
- charge/discharge efficiency: **0.95 / 0.95** (`ASSUMED_EXPLORATORY`);
- SOC initial/min/max: **0.90 / 0.20 / 0.90** (`ASSUMED_EXPLORATORY`).

This is not flight sizing.

### 6.3 PWR1 reserve-aware admission challenge

The first myopic admission policy permitted true housekeeping power deficits in 140/240 constrained smoke runs. A follow-up changed **only the admission policy**, keeping the same hardware.

A0-R protects battery energy required to supply mandatory housekeeping until the next deterministic generation opportunity:

\[
E_{protected}=SOC_{min}E_{capacity}+\frac{P_{house}\,t_{next-generation}}{\eta_{discharge}}
\]

Compute may use only battery energy above this protected level.

In the frozen 10-seed PWR1 comparison:

- A0-M myopic: **100/240 valid**, **140 SYSTEM_POWER_DEFICIT**;
- A0-R reserve-aware: **240/240 valid**, **0 SYSTEM_POWER_DEFICIT**.

The cost was additional compute denial in several workload/environment combinations. The thermal effect changed only by millikelvin-scale amounts for W2/W3 and essentially not at all for W1/W4/W5 in that campaign.

For E1 closed-loop W5 under A0-R at the original epoch:

- median peak node temperature: approximately **348.201 K**;
- median ΔT vs W0: approximately **16.626 K**;
- median FDIR events: **1**;
- median thermal-throttle time: approximately **85 s**;
- median FDIR-denied compute energy: approximately **2.371 MJ**.

This is not evidence that a real spacecraft controller would behave the same way. It shows only that the modelled coupling survives this particular essential-load-preserving resource-control wrapper.

---

## 7. RSIM-001-EPOCH1: relative orbital epoch challenge

EPOCH1 changes one independent variable: the relative E1 orbital phase offset. The requested W0–W5 traces are kept byte-identical across offsets.

Frozen offsets:

`0°, 45°, 90°, 135°, 180°, 225°, 270°, 315°`

Campaign:

- 10 seeds;
- 6 workloads;
- 8 epoch offsets;
- POWER_CONSTRAINED and CLOSED_LOOP;
- **960/960 valid runs**;
- **0 SYSTEM_POWER_DEFICIT**.

### 7.1 W5 phase-shaped candidate

Across all 80 paired seed×epoch observations:

| Mode | Mean ΔT | Median ΔT | Min | Max |
|---|---:|---:|---:|---:|
| POWER_CONSTRAINED | 14.719 K | 16.073 K | 10.625 K | 16.802 K |
| CLOSED_LOOP | 14.663 K | 16.061 K | 10.625 K | 16.647 K |

No W5 paired ΔT is zero or negative in the eight sampled epochs.

Closed-loop epoch medians range from approximately **10.635 K at 180°** to **16.636 K at 315°**.

However, throughput cost is strongly epoch dependent. W5 reserve-induced compute denial is near zero at some epochs and exceeds 100 MJ at the most constrained offsets. Lower-temperature epochs often coincide with more denied compute, but denial alone does not explain the full response: high denial can coexist with a large ΔT at another epoch.

### 7.2 W4 benign power-aware comparator

Across 80 seed×epoch observations, W4 ΔT has:

- mean approximately **7.897 K**;
- median approximately **9.308 K**;
- minimum approximately **0.538 K**;
- maximum approximately **10.211 K**.

W4 therefore has a wider relative epoch response than W5 and nearly loses the effect at the 135° epoch without changing sign.

### 7.3 W1–W3

Epoch sensitivity is not unique to W5:

- W1 remains narrow, roughly **1.76–2.00 K** across paired observations;
- W2 spans roughly **1.75–10.70 K**;
- W3 spans roughly **3.85–13.71 K**.

This is important to the review. The project does not interpret epoch sensitivity as attack-specific. It is evidence that temporal workload structure and environment alignment jointly affect peak state inside the current reduced-order plant.

---

## 8. Current strongest model-conditional interpretation

The most defensible current statement is:

> **Within the tested TSM-01/RSIM assumptions, temporal workload structure remains coupled to peak thermal state across multiple workload families, a component-based analytic LEO forcing, essential-load-preserving electrical admission, simplified thermal protection, and eight sampled relative orbital epochs. The magnitude and throughput cost are architecture- and epoch-dependent.**

The project does **not** claim that the 10–17 K W5 range, the W4 range, or the observed FDIR behaviour is physically transferable to a real spacecraft.

The unresolved question for the reviewer is therefore now sharper:

> **Could the present two-node thermal abstraction itself be creating or materially amplifying this persistent timing sensitivity?**

---

## 9. Questions for the independent thermal reviewer

Please answer these in `REVIEW_FORM_v2.md`.

### Model form and timescales

1. Is a two-node compute/cold-plate ↔ radiator model adequate for screening temporal workload/thermal coupling at multi-minute to orbital timescales?
2. Which minimum additional thermal state(s) are required before the magnitude should be interpreted quantitatively?
3. Could a single effective `UA = 3000 W/K` materially distort phase lag or peak timing compared with a pumped loop, heat pipe, or other transport architecture?
4. Could explicit coolant inventory/transport delay reduce, increase, or reverse the workload ordering?
5. Is a single radiator capacitance likely to overstate or understate peak response because real radiator panels/manifolds are distributed systems?
6. Is the ratio of the model thermal time constants to a ~90–96 min LEO period physically plausible for the class of system being screened?

### Environment and radiation

7. Is E1's separation of direct solar, Earth albedo and Earth IR a reasonable screening improvement over E0, despite its effective geometry factors?
8. Are fixed `C_rad,sun = 0.25` and `F_E,rad = 0.50` acceptable only as sensitivity parameters, or too unconstrained for quantitative use?
9. Which omitted environmental effect is most likely to change the sign/order/magnitude: beta angle, attitude, radiator view factors, eclipse transition, Earth IR spatial variation, albedo geometry, self-view, or another term?
10. Would a segmented radiator with spatially nonuniform absorbed flux likely change the epoch sensitivity materially?

### Power-to-heat representation

11. Is treating executed compute electrical power as immediate heat generation acceptable for this screening fidelity?
12. What minimum workload→electrical-power→heat measurement campaign is required before the reported multi-kelvin magnitudes are meaningful?
13. Which dynamics are most important: DVFS/boost, package capacitance, PSU conversion loss, delayed heat release, cold-plate resistance, coolant flow, or another mechanism?

### Protection and resource control

14. Does reserve-aware electrical admission remove an obvious architectural impossibility, or does it introduce assumptions that should be represented differently?
15. Is the current threshold/latency/12-kW monotone thermal limiter useful only as a software-control probe, or can it approximate any credible spacecraft protection behaviour?
16. What minimum thermal-protection model is required before discussing containment rather than only peak-state coupling?

### Interpretation / falsification

17. Does equal cumulative energy producing different peak temperature under time-varying boundary conditions make physical sense at this abstraction level?
18. Are excursions on the order currently observed in TSM-01/RSIM physically plausible, or are they likely dominated by the chosen lumped capacitances/conductance/environment assumptions?
19. What missing physics could cause a workload that currently produces a larger peak to produce a smaller peak in a more realistic model?
20. What is the single strongest model or experiment that would falsify or materially weaken the present interpretation?

### Next fidelity

21. What is the minimum next model you recommend: revised two-node, 3-node, 4–8-node lumped network, explicit fluid-loop state, segmented radiator, geometry-resolved model, or another topology?
22. Which parameters must be grounded before that model should be run?
23. What evidence would you require before HIL?
24. What evidence would you require before thermal-vacuum/model-correlation work?

---

## 10. Finding severity

Use these only as project bookkeeping; the reviewer may substitute another scheme.

- **Critical:** likely to invalidate, reverse, or make quantitatively uninterpretable the central timing result.
- **Major:** likely to materially change magnitude or applicability, but does not necessarily invalidate existence of the coupling.
- **Minor:** correction/refinement unlikely to change the central screening conclusion.
- **Suggestion:** useful improvement not required for present screening interpretation.

---

## 11. Project action after review

- **Disposition A:** retain TSM-01 only as a screening baseline; next work becomes parameter grounding, representative workload→power measurement, global sensitivity, then minimum reviewer-recommended multi-state extension.
- **Disposition B:** resolve all Critical/Major model-form findings before stronger quantitative interpretation or additional large campaigns.
- **Disposition C:** stop quantitative thermal-security interpretation, rebuild the thermal plant at the reviewer-recommended minimum fidelity, then rerun the frozen workload/RSIM protocols against that new plant.

A negative review is an acceptable and useful result.

---

## 12. Repository evidence for review

Primary source-of-truth files:

- `src/octm/baselines/v044/thermal_model.py`
- `src/octm/baselines/v044/run_all_v044.py`
- `results_v044.json`
- `RELEASE_NOTES_v0.4.4.md`
- `results/baseline_v044_verification.json`
- `experiments/WRB-001/README.md`
- `results/WRB-001/summary.json`
- `experiments/RSIM-001/README.md`
- `evidence/rsim001_parameters.json`
- `results/RSIM-001-smoke/summary.json`
- `results/RSIM-001-PWR1/summary.json`
- `results/RSIM-001-PWR1/comparison_A0M_A0R.json`
- `results/RSIM-001-EPOCH1/summary.json`
- `results/RSIM-001-EPOCH1/epoch_response.json`
- `results/RSIM-001-EPOCH1/invariants.json`

The historical `legacy/reconstructed_v044/VALIDATION.md` is retained only for provenance and is not an independent spacecraft-thermal review.