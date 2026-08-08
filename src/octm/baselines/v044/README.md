# TSM-01 / OCTM v0.4.4 reproducibility package

This package supports **Orbital Compute Cyber-Physical Threat Model v0.4.4**.
It is vendor-independent. Numerical findings are project-generated modelling
evidence, not independent spacecraft-thermal validation.

## Release integrity first

Review and reproduction should use the **complete release ZIP**, not loose files.
After extraction, verify the release before running any script:

```bash
sha256sum -c MANIFEST.sha256
```

Only continue if the manifest passes.

## Authoritative workflow

```bash
python -m pip install -r requirements.txt
python run_all_v044.py      # generates the single authoritative results_v044.json
python plot_results.py      # generates all five document figures from v0.4.4 inputs/results
```

`run_all_v044.py` is the only normative numerical campaign in this release.
Legacy v0.4-v0.4.3 numerical campaign scripts are not included in the normative
package. The source model remains `thermal_model.py`.

## Environment used for the release

- Python 3.13.5
- NumPy 2.3.5
- Matplotlib 3.10.8
- Numba 0.65.1

Exact PNG bytes can depend on the OS/font/rendering stack. The release therefore
claims **numerical reproducibility in the recorded dependency environment**, not
cross-platform byte-identical graphics.

## v0.4.4 interpretation guardrails

- TSM-01 is a two-node parametric model, not a digital twin.
- The main retained result is a **thermal-safety/resource-control coupling**:
  workload timing changes peak model temperature at matched sampled energy.
- A separately generated, non-malicious synthetic power-aware schedule produces
  84.0% of the full phase-shaped peak excursion in this model. This is a
  synthetic counterexample, not an empirical production workload trace.
- The 12 sensitivity entries are **10 single-factor cases + 1 joint radiator
  area/emissivity case + 1 baseline reference**. The full 8.03-23.68 K observed
  range is set by power-related assumptions, not by the thermal-design slices.
- The deterministic numerical-convergence experiment uses fixed, noise-free
  forcing. The separate release-step/realisation table for the stochastic
  headline experiment is a mixed sensitivity check and is **not** convergence.
- Parameters marked ASSUMED in Appendix A are not source-backed measurements.
- 75 C and 90 C are project-assumed model thresholds, not generic hardware limits.
- The uncertainty distributions are illustrative project assumptions.
- P0-P2 and E0-E4 are project-defined labels, not SPARTA/NASA/NIST scales.
- No independent spacecraft-thermal review has yet been completed.

## Distribution rule

The release ZIP is the authoritative review object. Individual DOCX/JSON files
may be provided as convenience mirrors, but they are not a substitute for the
manifested package.
