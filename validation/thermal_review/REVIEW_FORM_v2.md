# OCTM Independent Spacecraft-Thermal Review Form v2

**Model reviewed:** TSM-01 v0.4.4 canonical two-node thermal plant  
**Companion evidence:** WRB-001 + non-authoritative RSIM-001/PWR1/EPOCH1 representative challenges  
**Companion package:** `REVIEW_PACKAGE_v2.md`

Completing this form does **not** imply endorsement of OCTM, a cyberattack claim, a vulnerability, or a deployed spacecraft architecture.

---

## A. Reviewer information and independence

**Reviewer name:**  
**Affiliation / role:**  
**Relevant spacecraft-thermal experience:**  
**Relevant model-correlation / TVAC / thermal-transport experience:**  
**Date:**  
**Approximate review time:**  

**Conflict / prior involvement:**

- [ ] I had no role in constructing TSM-01, WRB-001 or RSIM-001.
- [ ] I have prior involvement; describe below.

Notes:


**Materials actually reviewed:**

- [ ] `REVIEW_PACKAGE_v2.md`
- [ ] `src/octm/baselines/v044/thermal_model.py`
- [ ] `results_v044.json`
- [ ] `results/WRB-001/summary.json`
- [ ] `experiments/RSIM-001/README.md`
- [ ] `evidence/rsim001_parameters.json`
- [ ] `results/RSIM-001-PWR1/summary.json`
- [ ] `results/RSIM-001-EPOCH1/summary.json`
- [ ] `results/RSIM-001-EPOCH1/epoch_response.json`
- [ ] Other: ______________________________

**Independent calculations/tools used, if any:**


---

## B. Final disposition

Select one:

- [ ] **A — Suitable for screening as currently formulated.**
- [ ] **B — Suitable for screening after major revisions.**
- [ ] **C — Not suitable for quantitative screening in its current form.**
- [ ] Other: __________________________________________

**Rationale:**


**May the project continue to report the existing WRB/RSIM numerical values only as model-conditional screening results while retaining all current limitations?**

- [ ] Yes
- [ ] Yes, only after Critical/Major findings below are resolved
- [ ] No

---

## C. Finding summary

| ID | Severity | Topic | Finding | Required action/evidence | Blocks quantitative interpretation? |
|---|---|---|---|---|---|
| TH-01 |  |  |  |  |  |
| TH-02 |  |  |  |  |  |
| TH-03 |  |  |  |  |  |
| TH-04 |  |  |  |  |  |
| TH-05 |  |  |  |  |  |
| TH-06 |  |  |  |  |  |

Severity:

- **Critical:** likely to invalidate, reverse, or make quantitatively uninterpretable the timing result.
- **Major:** likely to materially change magnitude/applicability.
- **Minor:** unlikely to change the central screening conclusion.
- **Suggestion:** useful improvement not required for current screening interpretation.

---

## D. Thermal model form

### D1. Two-node abstraction

Is compute/cold-plate ↔ radiator an acceptable reduced-order topology for screening temporal workload/thermal coupling at multi-minute to orbital timescales?

- [ ] Yes
- [ ] Yes with qualifications
- [ ] No

Technical basis:


### D2. Minimum missing state(s)

Select all states required **before quantitative magnitude interpretation**:

- [ ] None for screening
- [ ] Package/device thermal state
- [ ] Cold-plate state
- [ ] Coolant inventory state
- [ ] Explicit transport-delay state
- [ ] Pump/flow/transport-capacity state
- [ ] Heat exchanger state
- [ ] Spacecraft bus/structure state
- [ ] Multiple radiator segments
- [ ] Multiple compute nodes
- [ ] Other: ______________________________

Expected effect on phase lag, peak timing and magnitude:


### D3. Effective conductance

Is `UA = 3000 W/K` usable as an explicitly effective screening parameter?

- [ ] Yes
- [ ] Only after calibration/first-principles grounding
- [ ] No; explicit transport states are required

Could realistic transport delay or flow dynamics reverse the present workload ordering?


### D4. Radiator lumping

Could one radiator capacitance materially distort the response because of panel segmentation, manifolds, local gradients, deployment geometry or changing view factors?

- [ ] Unlikely at screening level
- [ ] Possibly material
- [ ] Likely material

Comments:


### D5. Thermal timescales

Are the implied TSM-01 time constants physically plausible relative to a ~90–96 minute LEO period for the system class being screened?

- [ ] Yes
- [ ] Plausible but needs evidence
- [ ] No

Recommended timescale checks/calculations:


---

## E. Parameter plausibility

| Parameter group | Suitable for screening | Needs stronger evidence | Not defensible | Suggested range/source/evidence |
|---|:---:|:---:|:---:|---|
| Radiator area / emissivity | [ ] | [ ] | [ ] | |
| Compute-node capacitance | [ ] | [ ] | [ ] | |
| Radiator capacitance | [ ] | [ ] | [ ] | |
| Effective `UA` | [ ] | [ ] | [ ] | |
| 40 kW design compute | [ ] | [ ] | [ ] | |
| 30 kW average compute | [ ] | [ ] | [ ] | |
| 2 kW housekeeping heat | [ ] | [ ] | [ ] | |
| Canonical 150/40 W/m² environment | [ ] | [ ] | [ ] | |
| E1 radiator absorptivity / incidence | [ ] | [ ] | [ ] | |
| E1 Earth-view factor | [ ] | [ ] | [ ] | |
| A0 electrical sizing assumptions | [ ] | [ ] | [ ] | |
| Initial thermal conditions / warmup | [ ] | [ ] | [ ] | |
| 75 °C project throttle assumption | [ ] | [ ] | [ ] | |

**Three thermal parameters to ground first:**

1. 
2. 
3. 

**Preferred evidence:** first-principles / datasheet / bench / HIL / thermal-vac correlation / other.

---

## F. Environment and radiation

### F1. E0 versus E1

Does separating direct solar, albedo and Earth IR in E1 make the environment materially more useful for screening than the canonical two-level E0?

- [ ] Yes
- [ ] Yes, but geometry assumptions still dominate
- [ ] No

Comments:


### F2. Effective radiator geometry

E1 uses exploratory effective factors `C_rad,sun = 0.25` and `F_E,rad = 0.50`.

How should these be treated?

- [ ] Acceptable nominal sensitivity parameters
- [ ] Require broad sensitivity sweep before using magnitudes
- [ ] Too unconstrained; replace with attitude/geometry-derived factors
- [ ] Other: ______________________________

### F3. Missing environmental physics

Rank the three most important omissions:

1. 
2. 
3. 

Candidates: beta angle, attitude history, eclipse transition/penumbra, radiator self-view, Earth IR spatial/seasonal variation, albedo geometry, spacecraft shadowing, radiator segmentation, other.

### F4. Epoch sensitivity

EPOCH1 shows that changing only relative orbital epoch changes W4/W5 magnitude while retaining positive paired ΔT in the sampled offsets.

Is that qualitatively expected for a time-varying boundary-condition problem?

- [ ] Yes
- [ ] Yes, but the magnitude is not interpretable
- [ ] No / concerning

Could a better environment model plausibly reverse the sign/order?


---

## G. Workload → electrical power → heat

### G1. Immediate heat-input assumption

Is using executed compute electrical power as immediate compute-node heat input acceptable for screening?

- [ ] Yes
- [ ] Yes if conversion/non-compute losses are explicit
- [ ] No; additional dynamic states are required

### G2. Required hardware measurements

Select what should be measured before stronger magnitude claims:

- [ ] idle power
- [ ] sustained load power
- [ ] burst response
- [ ] DVFS / boost transitions
- [ ] power-cap response
- [ ] thermal-throttle response
- [ ] workload-class dependence
- [ ] PSU/conversion losses
- [ ] package/cold-plate temperature difference
- [ ] coolant inlet/outlet temperature
- [ ] coolant flow / transport capacity
- [ ] other: ______________________________

Recommended sampling rate/test duration:


### G3. Likely effect of realistic compute controls

Would DVFS, power caps, scheduling smoothing, package capacitance or power-delivery dynamics likely:

- [ ] materially reduce timing sensitivity
- [ ] materially increase timing sensitivity
- [ ] change magnitude but probably not existence
- [ ] cannot determine without measurement

Technical basis:


---

## H. Power-system admission and protection

### H1. Reserve-aware admission

A0-R reserves enough battery energy for mandatory housekeeping until the next deterministic generation opportunity and eliminated housekeeping deficits in the tested PWR1 matrix without changing hardware.

Does this remove an obvious resource-control artefact for screening?

- [ ] Yes
- [ ] Partially
- [ ] No

What electrical-control behaviour should replace or augment it in a more representative architecture?


### H2. Thermal limiter

The RSIM limiter retains project-assumed 348.15 K arming, 5 K hysteresis, configurable latency and a 12 kW monotone compute limit.

At this stage it should be interpreted as:

- [ ] useful software/control probe only
- [ ] rough screening analogue of thermal protection
- [ ] not useful without a more representative control model

Comments:


### H3. Minimum credible thermal protection model

Select required functions before a safety-containment claim:

- [ ] filtering
- [ ] sensor voting/redundancy
- [ ] warning state
- [ ] progressive throttling
- [ ] emergency workload shedding
- [ ] scheduler admission
- [ ] hysteresis/recovery
- [ ] safe mode
- [ ] independent safety authority
- [ ] actuator delay/failure
- [ ] telemetry delay/failure
- [ ] other: ______________________________

---

## I. Interpretation of the numerical evidence

### I1. WRB-001 qualitative result

Does equal requested cumulative compute energy producing different peak temperature under time-varying boundary conditions make physical sense?

- [ ] Yes
- [ ] Yes, but magnitude is not yet interpretable
- [ ] No

Comments:


### I2. RSIM persistence

The coupling remains present after adding E1, reserve-aware admission and eight relative epochs. Does this materially increase confidence that the effect is not merely a square-wave or myopic-power-admission artefact?

- [ ] Yes, as internal model evidence only
- [ ] Only weakly
- [ ] No

Explain:


### I3. Magnitude plausibility

W5 closed-loop paired epoch results span roughly 10.6–16.6 K versus W0; W4 spans roughly 0.54–10.21 K.

Are excursions of these orders of magnitude physically plausible for a representative high-power spacecraft thermal architecture?

- [ ] Plausible order of magnitude
- [ ] Possibly, but current parameters are too weakly grounded
- [ ] Likely overstated
- [ ] Likely understated
- [ ] Cannot assess without a different model

Reason:


### I4. Ordering reversal

What real thermal mechanism could cause a workload that produces a larger peak in TSM-01 to produce a smaller peak in a more realistic model?


### I5. Strongest falsification test

What single experiment/model extension would most strongly falsify or materially weaken the present interpretation?


---

## J. Recommended next fidelity

Select the **minimum** useful next step:

- [ ] Keep two-node model; improve parameter evidence only
- [ ] Revised 3-node model
- [ ] 4–8-node lumped compute/shared-loop/radiator model
- [ ] Explicit pumped-loop dynamic model
- [ ] Segmented radiator model
- [ ] Geometry/attitude-resolved thermal model
- [ ] Hardware workload→power measurement before plant expansion
- [ ] HIL/FlatSat before further thermal expansion
- [ ] Other: ______________________________

**Recommended minimum topology/state list:**


**Parameters that must be grounded before building it:**


**Acceptance criterion before HIL:**


**Acceptance criterion before thermal-vac/model correlation:**


---

## K. Reviewer sign-off

Select or replace with your own wording:

- [ ] I reviewed the supplied material as a spacecraft-thermal model-form screening package. My conclusions apply only to the stated model and assumptions.
- [ ] I reviewed selected portions only; see limitations below.

**Review limitations:**


**Reviewer name/signature or typed acknowledgement:**  
**Date:**
