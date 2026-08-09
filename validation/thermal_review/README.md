# Independent spacecraft-thermal review

This directory contains the material prepared for a future independent spacecraft-thermal SME model-form review of OCTM/TSM-01.

## Current review package

- `REVIEW_PACKAGE_v2.md` — current technical review package. It covers the canonical TSM-01 v0.4.4 plant, WRB-001, the RSIM-001 representative architecture challenge, reserve-aware power admission (PWR1), and the eight-epoch EPOCH1 challenge.
- `REVIEW_FORM_v2.md` — current structured reviewer response and finding-disposition form.

## Historical package

- `REVIEW_PACKAGE_v1.md` — pre-RSIM package retained for provenance.
- `REVIEW_FORM_v1.md` — matching v1 reviewer form retained for provenance.

## Status

**No independent spacecraft-thermal review is recorded yet.** The presence of these files means only that review material has been prepared.

The reviewer is asked to assess whether the two-node reduced-order thermal plant is physically suitable for screening workload-timing → thermal-state coupling, whether the current quantitative magnitudes are interpretable, which missing states/timescales/geometry assumptions could materially alter or reverse the result, and what minimum next thermal fidelity should be built.

The reviewer is **not** being asked to endorse a cyberattack, vulnerability claim, spacecraft design, orbital data center, or deployed architecture.

The RSIM evidence is explicitly non-authoritative and does not convert TSM-01 into a validated spacecraft model. It is included because it tests whether the modelled coupling survives several internal architecture challenges before external physical review.

The historical reconstruction-validation record is retained separately at `legacy/reconstructed_v044/VALIDATION.md` and is not an independent thermal review.
