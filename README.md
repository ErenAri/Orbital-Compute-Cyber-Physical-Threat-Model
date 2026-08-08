# OCTM v0.4.4 canonical baseline and WRB-001

This repository retains the frozen OCTM/TSM-01 v0.4.4 publication artefacts
and the manifested canonical source baseline under
`src/octm/baselines/v044/`. The source files are authoritative and their
SHA-256 values are checked against `MANIFEST.sha256`.

WRB-001 calls the canonical thermal model through
`src/octm/adapters/v044.py`. The adapter supplies array/RNG compatibility and
paired-energy bookkeeping; it does not change the frozen physics,
environmental forcing, parameters, workload formulas, measurement window, or
Forward-Euler integration semantics.

The earlier reconstructed implementation and results remain under
`legacy/reconstructed_v044/` and `results/WRB-001-reconstructed/` solely for
provenance and migration comparison. Canonical `results/WRB-001/` supersedes
those reconstructed campaign results.

## Reproduce

```text
python -m pip install -r requirements-wrb.txt
python verify_baseline_v044.py
python run_wrb_001.py
python compare_wrb_001_migration.py
python plot_wrb_001.py
python -m pytest -q
```

The campaign characterizes timing sensitivity in a two-node parametric model.
It does not validate an attack, vulnerability, spacecraft thermal design, or
deployed orbital-compute architecture.
