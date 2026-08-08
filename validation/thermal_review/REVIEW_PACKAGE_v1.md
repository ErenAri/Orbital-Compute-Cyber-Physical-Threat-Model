# OCTM Independent Spacecraft-Thermal Model Review Package v1

**Project:** Orbital Compute Cyber-Physical Threat Model (OCTM)  
**Model under review:** TSM-01 v0.4.4 canonical two-node thermal model  
**Review type requested:** independent spacecraft-thermal **model-form and assumption review**  
**Review status:** request package only; no independent review or endorsement is recorded by this document  
**Date:** 8 August 2026

---

## 1. Decision requested from the reviewer

OCTM is investigating whether **temporal placement of compute workload** can materially change peak thermal state even when sampled cumulative compute energy is held equal over the comparison window.

The project is **not** asking the reviewer to validate a cyberattack, vulnerability, spacecraft design, or orbital-data-centre architecture. The requested decision is narrower:

> **Is the TSM-01 two-node reduced-order thermal model physically appropriate for screening the workload-timing → thermal-state coupling question, and what missing states, time constants, parameter assumptions, or protection mechanisms could materially change or invalidate the quantitative result?**

Please evaluate the model as a screening abstraction, not as a flight-qualified thermal design model.

### Requested final disposition

Choose one in `REVIEW_FORM_v1.md`:

- **A — Suitable for screening as currently formulated.** The abstraction is adequate for the stated research question, subject to documented limitations.
- **B — Suitable for screening after major revisions.** The underlying question is meaningful, but specific model-form changes are required before quantitative interpretation.
- **C — Not suitable for quantitative screening in its current form.** Missing physics or architecture assumptions are likely to dominate or reverse the reported effect.

The reviewer is encouraged to recommend a different minimum-fidelity model if none of these labels captures the technical judgment.

---

## 2. Research question and claim boundary

### 2.1 Research question

The current research question is:

> Under what spacecraft architectures and workload/control assumptions does temporal compute placement materially change physical thermal safety margins, and when could a software-controlled scheduling authority intentionally or unintentionally exploit that coupling despite onboard safety controls?

The first part—whether the physical coupling exists under a defensible thermal abstraction—must be established before any stronger security interpretation.

### 2.2 What the current evidence supports

Within the **canonical TSM-01 v0.4.4 assumptions**, equal sampled compute-energy budgets can yield materially different peak compute-node temperatures when workload timing changes relative to the modelled orbital thermal environment.

WRB-001 extends the earlier single-comparator result across six workload families and 100 paired seeds. The campaign is classified `ROBUST` under its preregistered exploratory rule because the phase-shaped candidate and multiple benign workload families remain materially different from the constant reference.

### 2.3 What the current evidence does not support

The project does **not** currently claim that:

- a deployed spacecraft or orbital-compute platform has this vulnerability;
- the TSM-01 parameter set represents any named company or flight architecture;
- the two-node model is a digital twin or flight-correlated thermal model;
- the reported temperature excursions are transferable to real hardware;
- the phase-shaped workload is a validated attack path;
- the model establishes hardware damage or a universal safety-threshold violation;
- the current detector or protection examples are flight-ready FDIR designs.

The v0.4.4 source itself describes TSM-01 as a **project-generated parametric model, not a digital twin and not a validated spacecraft design model**.

---

## 3. Model boundary and governing equations

TSM-01 uses two lumped thermal nodes:

1. **Compute / cold-plate node** — receives compute power and a fixed housekeeping heat load.
2. **Radiator node** — exchanges heat conductively with the compute node, absorbs an idealised environmental heat flux, and rejects heat radiatively to deep space.

The canonical source implements the following balances:

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

where:

- \(C_{node}\) and \(C_{rad}\) are lumped thermal capacitances;
- \(UA\) is an effective node-to-radiator conductance;
- \(A\) is effective radiator area;
- \(q_{env}\) is a lumped absorbed environmental heat flux;
- \(\epsilon\) is effective IR emissivity;
- \(\sigma\) is the Stefan-Boltzmann constant;
- \(P_{compute}\) is the time-varying compute workload heat input;
- \(P_{house}\) is a fixed housekeeping heat input.

### 3.1 Environmental forcing

The current environment is deliberately simple:

- orbit period: **5400 s**;
- hot/sunlit fraction: **0.62**;
- hot absorbed flux: **150 W/m²**;
- cold absorbed flux: **40 W/m²**;
- phase zero begins the hot interval.

The forcing is therefore a two-level orbital heat-flux profile, not a geometry-, attitude-, eclipse-transition-, albedo-, Earth-IR-, beta-angle-, or view-factor-resolved environment.

### 3.2 Numerical integration

The canonical release uses Forward Euler integration. The release step is **1 s**. The standard experiment runs two warmup orbits and evaluates the following six complete orbits.

A deterministic noise-free convergence experiment in v0.4.4 used a 0.0625 s reference. At `dt = 1 s`, the reported peak-delta error relative to that reference is approximately **0.00176 K** for that fixed-forcing experiment. The release therefore treats the numerical step as a small error source relative to the multi-kelvin workload-timing effects observed in the parametric model; this statement is limited to the tested deterministic experiment.

---

## 4. Baseline parameter register for review

The values below are the canonical v0.4.4 baseline. Unless stated otherwise, they are **project assumptions**, not flight-calibrated properties.

| Parameter | Canonical value | Current evidence status | Review concern |
|---|---:|---|---|
| Effective radiator area \(A\) | 100 m² | Project-assumed | Is this a defensible scaling abstraction for a 40 kW-class compute load? |
| Effective IR emissivity \(\epsilon\) | 0.85 | Project-assumed | Is a single constant effective emissivity appropriate for screening? |
| Compute-node heat capacity \(C_{node}\) | 3.6×10⁵ J/K | Project-assumed | Does this lump too much or too little hardware/coolant mass? |
| Radiator heat capacity \(C_{rad}\) | 2.25×10⁵ J/K | Project-assumed | Is a single radiator capacitance adequate for orbital transients? |
| Effective conductance \(UA\) | 3000 W/K | Project-assumed | Can one conductance represent cold plate, coolant, transport and radiator coupling? |
| Housekeeping heat | 2000 W | Project-assumed | Should platform heat be applied at a separate node? |
| Compute design power | 40,000 W | Project-assumed | Power magnitude dominates the current local sensitivity campaign. |
| Diversified average compute power | 30,000 W | Project-assumed | Workload-to-power calibration is not hardware-derived. |
| Deep-space sink temperature | 3 K | Idealised boundary | Is this acceptable when environmental flux is represented separately? |
| Hot environmental flux | 150 W/m² | Project-assumed lumped flux | Should Earth IR, albedo, solar geometry and view factors be separated? |
| Cold environmental flux | 40 W/m² | Project-assumed lumped flux | Same concern as above. |
| Orbit period | 5400 s | Representative LEO assumption | Is 90 min adequate as a screening timescale? |
| Hot fraction | 0.62 | Project-assumed | How sensitive is the coupling to realistic eclipse/sunlight geometry? |
| Initial compute temperature | 320 K | Project-assumed; warmup used | Is two-orbit warmup sufficient to remove initial-condition bias? |
| Initial radiator temperature | 305 K | Project-assumed; warmup used | Same concern as above. |
| Throttle threshold | 348.15 K (75 °C) | **Project-assumed threshold** | Not a universal hardware limit. |
| Upper model limit | 363.15 K (90 °C) | **Project-assumed model limit** | Not a universal damage threshold. |
| Stefan-Boltzmann constant | 5.670374419×10⁻⁸ W m⁻² K⁻⁴ | Physical constant | No project calibration required. |

The v0.4.4 release notes cite an independent order-of-magnitude radiator-area-per-power comparison, but explicitly state that this does **not** validate TSM-01 dynamics or its exact parameters. The reviewer should therefore treat the parameter set as an open engineering question.

---

## 5. Canonical reproducibility status

Before the external model-form review, the project corrected the WRB-001 validation campaign to use the manifested canonical v0.4.4 source directly.

Current repository checks establish:

- canonical release manifest: **15/15 SHA-256 entries present and matching**;
- regenerated v0.4.4 scientific/numerical content: **364/364 values exactly equal** to the authoritative result set;
- maximum scientific numerical difference: **0.0**;
- canonical WRB-001 campaign: **100 paired seeds, 600/600 valid runs**;
- WRB-001 scientific outputs are deterministic across repeated authoritative runs.

These checks establish implementation and release provenance. They **do not** establish physical validity. Physical/model-form validity is the purpose of this review.

Primary repository evidence:

- `src/octm/baselines/v044/thermal_model.py`
- `src/octm/baselines/v044/run_all_v044.py`
- `src/octm/baselines/v044/MANIFEST.sha256`
- `results_v044.json`
- `results/baseline_v044_verification.json`
- `experiments/WRB-001/README.md`
- `results/WRB-001/summary.json`

---

## 6. WRB-001 workload-robustness experiment

### 6.1 Experimental control

WRB-001 asks whether the timing effect is tied to one synthetic waveform or persists across different workload structures.

For each seed:

- all workloads use the same deterministic physical/environmental realisation;
- workload RNG streams are explicit and order-independent;
- the post-warmup measurement window is identical;
- the sampled compute-energy target is the canonical diversified workload (W1) for that seed;
- W0 and W2–W5 are energy matched to that target;
- invalid energy matching is explicit rather than silently clipped.

The canonical campaign uses seeds `0..99`, `dt = 1 s`, two warmup orbits and six measurement orbits.

### 6.2 Workload families

| ID | Workload | Information available to scheduler/generator | Interpretation |
|---|---|---|---|
| W0 | `constant_reference` | W1 mean power target | Reference only |
| W1 | `diversified_stochastic` | Time + explicit RNG in canonical `load_nominal` | Synthetic benign comparator |
| W2 | `bursty_benign` | Own RNG only; no orbital/thermal input | Synthetic benign workload |
| W3 | `queue_driven_benign` | Synthetic arrivals/backlog; no orbital/thermal input | Synthetic benign scheduler |
| W4 | `power_aware_benign` | Time, own RNG, dimensionless electrical-availability signal | Synthetic benign power-aware scheduler; cannot observe thermal state or hot-phase indicator |
| W5 | `phase_shaped_candidate` | Canonical hot-phase convention | Adversarial **candidate**, not validated attack |

### 6.3 Canonical result

Median peak-temperature excursion relative to the constant reference:

| Workload | Median ΔT vs W0 | Bootstrap 95% CI for median | Notes |
|---|---:|---:|---|
| W0 constant | 0.000 K | 0.000–0.000 K | Reference |
| W1 diversified | **1.892 K** | **1.887–1.904 K** | Canonical v0.4.4 `load_nominal` |
| W2 bursty benign | **8.063 K** | **7.523–8.271 K** | Broad seed-to-seed variability |
| W3 queue-driven benign | **8.184 K** | **7.587–8.598 K** | Broad seed-to-seed variability |
| W4 power-aware benign | **10.439 K** | **10.437–10.440 K** | Synthetic availability-driven schedule |
| W5 phase-shaped candidate | **17.377 K** | **17.375–17.378 K** | Canonical phase-shaped candidate |

The current exploratory campaign label is **ROBUST** because W5 and at least two benign workload families are material under the preregistered campaign rule. `ROBUST` is a campaign classification, not a hardware safety or security certification.

### 6.4 Important interpretation detail

The original v0.4.4 headline experiment reported a **15.4609 K** energy-matched peak difference between its nominal and phase-shaped traces. WRB-001 reports a **17.377 K median W5 excursion relative to W0**, and approximately **15.484 K relative to W1**. These are not contradictory values: WRB-001 changes the reference definition and runs a paired 100-seed campaign rather than reusing one historical comparison as the sole headline.

The W4/W5 excursion ratio relative to W0 has median approximately **0.6007**. Relative to W1, the corresponding median ratio is approximately **0.5517**. The earlier v0.4.4 single-run value near 84% should therefore not be interpreted as a stable physical constant; reference definition and workload realisation materially affect that ratio.

### 6.5 Safety-threshold observation

Under the canonical WRB-001 baseline parameters, the tested workloads record **zero time above the project-assumed 75 °C throttle threshold and zero time above the project-assumed 90 °C upper model limit**. The experiment therefore demonstrates a modelled **peak-state and margin coupling**, not a baseline threshold breach.

That distinction is central to the requested review.

---

## 7. Existing sensitivity and numerical evidence

The v0.4.4 local sensitivity campaign contains 12 entries: **10 single-factor cases, 1 joint radiator-area/emissivity case, and 1 baseline reference**.

Observed local spans in peak-temperature difference:

| Parameter group | Observed span |
|---|---:|
| Radiator area/emissivity slice | **2.63 K** |
| Compute-node capacitance | **3.01 K** |
| Effective conductance | **3.59 K** |
| Orbit period | **3.22 K** |
| Power assumptions | **15.65 K** |

The overall tested range is **8.03–23.68 K**, and both extremes are power-related cases. The project therefore treats workload/power calibration as a higher-priority uncertainty than small refinements to low-sensitivity parameters.

These spans are **local tested slices, not global uncertainty bounds**. Interactions are not comprehensively explored. A future uncertainty campaign is expected to require global sensitivity methods and parameter evidence stronger than the current project assumptions.

---

## 8. Current protection / FDIR abstraction

The canonical thermal model contains an optional simplified thermal-protection mechanism with:

- a project-assumed throttle threshold;
- a latency before shedding;
- a fixed shed-power state;
- hysteresis for recovery.

This is useful for controlled experiments but is **not presented as representative spacecraft FDIR**.

The current research program expects a later control-system model to include, where appropriate:

- sensor filtering and voting;
- warning and throttle states;
- emergency workload shedding;
- hysteresis and recovery;
- safe mode;
- scheduler admission control;
- actuator and telemetry delay/failure modes;
- independent safety authority separated from tenant/workload control.

A reviewer finding that realistic thermal protection would dominate the tested timing effect is a valuable result and should be stated explicitly.

---

## 9. Known model-form omissions to challenge

The project specifically asks the reviewer to challenge whether any of the following omissions make the current quantitative result misleading:

1. **Single effective transport conductance.** No explicit coolant/fluid inventory, cold-plate dynamics, heat exchanger, pump curve, transport delay, saturation, or two-phase behaviour.
2. **Single radiator node.** No panel segmentation, manifold distribution, local hot spots, deployment geometry, structural gradients, or changing view factors.
3. **Single compute node.** No server/accelerator/package hierarchy, multiple racks/boards, local cold-plate resistance, or workload placement among physical nodes.
4. **Compute power treated as heat input.** No hardware-derived workload→electrical-power→heat calibration, DVFS/boost dynamics, PSU conversion losses, transient capacitance or delayed heat release.
5. **Simplified orbital environment.** Two-level heat flux rather than attitude/geometry-resolved solar, albedo, Earth IR and eclipse transitions.
6. **Fixed material/effective properties.** No temperature dependence, degradation, contamination or thermal-optical property evolution.
7. **No explicit spacecraft bus coupling.** Housekeeping heat is injected at the compute node and there is no separate structure/bus node.
8. **No detailed closed-loop thermal control.** Current protection logic is intentionally simplified.
9. **No hardware/test correlation.** No HIL, thermal-vacuum or flight correlation currently exists.
10. **No architecture-specific validation.** TSM-01 is vendor-independent and deliberately not calibrated to a named platform.

The reviewer should identify additional missing states or timescales not listed here.

---

## 10. Questions for the independent thermal reviewer

Please answer these directly in `REVIEW_FORM_v1.md`.

### Model form

1. Is a two-node compute/cold-plate ↔ radiator abstraction acceptable for **screening** temporal workload/thermal coupling at multi-minute to orbital timescales?
2. What minimum additional state(s) are required before the model should be interpreted quantitatively?
3. Is one effective `UA` an acceptable screening parameter, or does the transport system require explicit fluid/loop states even at this stage?
4. Is a single radiator capacitance materially misleading for the stated question?

### Parameter plausibility

5. Are the current orders of magnitude for `C_node`, `C_rad`, `UA`, radiator area and environmental flux physically plausible enough for screening?
6. Which parameters should be constrained from datasheets, first-principles estimates, bench measurements, or thermal correlation before any stronger claim?
7. Are the tested sensitivity ranges physically meaningful, too narrow, too broad, or missing key coupled ranges?

### Environment and timescales

8. Is the two-level hot/cold orbital forcing defensible for a first screening study?
9. Which orbital/environmental effects are most likely to alter the workload-timing coupling: eclipse transition, beta angle, attitude, Earth IR, albedo, solar view factor, radiator self-view, or another effect?
10. Is two-orbit warmup sufficient for this lumped system, and what criterion should be used instead of a fixed orbit count?

### Power and workload coupling

11. Is treating compute electrical power as immediate thermal input acceptable at this fidelity?
12. What workload→power→heat measurements would be necessary to calibrate a representative compute node?
13. Could realistic DVFS, boost, thermal throttling or power-delivery dynamics materially reduce or increase the reported timing sensitivity?

### FDIR / protection

14. Which thermal protection states and latencies would a credible spacecraft architecture normally require before this becomes a safety question rather than only a thermal-state question?
15. Could ordinary onboard protection be expected to contain the modelled excursions before a meaningful safety margin is consumed?

### Next fidelity step

16. If the two-node model is acceptable for screening, what is the **minimum useful next model**: 3-node, 4–8-node lumped network, explicit pumped loop, radiator segmentation, or another architecture?
17. What evidence would you require before recommending HIL or thermal-vacuum correlation?
18. What result would falsify or materially weaken the current workload-timing interpretation?

---

## 11. Proposed review severity definitions

Use the following project definitions so findings can be dispositioned consistently:

- **Critical:** model-form issue likely to invalidate, reverse, or make quantitatively uninterpretable the central workload-timing result. Quantitative security interpretation should stop until resolved.
- **Major:** material issue that can substantially change magnitude or applicability but does not necessarily invalidate the existence of the coupling.
- **Minor:** correction or refinement unlikely to change the central screening conclusion.
- **Suggestion:** useful future improvement, evidence request, or modelling preference that is not required to interpret the current screening result.

The reviewer may override these definitions if another classification scheme is preferred; please state the alternative explicitly.

---

## 12. Expected project action after review

The external review is a gating input, not an endorsement exercise.

- **If disposition A:** retain TSM-01 as a screening baseline; proceed to parameter grounding, hardware workload→power calibration, global sensitivity and a multi-node/shared-resource extension.
- **If disposition B:** implement and disposition all Critical/Major model-form findings before advancing quantitative interpretation.
- **If disposition C:** stop quantitative thermal-security interpretation, redesign the thermal plant at the reviewer-recommended minimum fidelity, and rerun the existing workload-robustness protocol on the new plant.

A negative review is an acceptable research result.

---

## 13. Source and provenance basis for this package

This package is derived from the current canonical repository state and does not add new flight-validation claims. Reviewers should use the following as the technical source of truth:

- `src/octm/baselines/v044/thermal_model.py` — canonical model equations, parameters, workloads and protection abstraction.
- `src/octm/baselines/v044/run_all_v044.py` — authoritative v0.4.4 experiment pipeline.
- `results_v044.json` — v0.4.4 authoritative numerical results and sensitivity accounting.
- `RELEASE_NOTES_v0.4.4.md` — release scope, corrections and limitations.
- `results/baseline_v044_verification.json` — canonical source/release reproducibility verification.
- `experiments/WRB-001/README.md` — paired-seed protocol and workload information boundaries.
- `results/WRB-001/summary.json` — canonical 100-seed WRB-001 results.
- `legacy/reconstructed_v044/VALIDATION.md` — historical reconstruction record retained only for provenance; not an independent thermal review.

The reviewer is not asked to accept repository reproducibility as evidence of physical correctness. Reproducibility and physical validity are separate gates.
