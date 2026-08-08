# WRB-001 — Paired-Seed Workload Robustness Campaign

WRB-001 characterizes workload-timing sensitivity using the canonical v0.4.4
TSM-01 two-node model. It does not validate an attack, a vulnerability, or a
deployed orbital-compute architecture.

## Baseline and migration provenance

The manifested sources in `src/octm/baselines/v044/` are the authoritative
scientific baseline. `src/octm/adapters/v044.py` converts WRB arrays into the
historical API and does not reimplement or modify the model. Run
`python verify_baseline_v044.py` first; WRB migration is valid only when
`results/baseline_v044_verification.json` reports `PASS`.

An earlier campaign used a transparent reconstruction because the historical
sources had not yet been supplied. Its implementation and outputs are retained
under `legacy/reconstructed_v044/` and `results/WRB-001-reconstructed/` for
provenance. They are non-authoritative. The canonical WRB-001 outputs under
`results/WRB-001/` supersede them.

## Pairing, RNG, and energy

Seeds 0–99 are authoritative. Each workload gets a stable child seed derived
from `(campaign, seed, workload id)`, independent of execution order. W1 passes
that explicit `numpy.random.Generator` directly to canonical `load_nominal`;
W5 passes its explicit generator to canonical `load_phase_locked`. Neither
wrapper uses hidden/global RNG state. Child seeds use the canonical source's
`default_rng`/PCG64 family and are recorded in every run.

Every paired workload shares the same deterministic physical/environmental
realization. Comparisons use the exact canonical half-open post-warmup interval:
two warmup orbits followed by six complete measurement orbits at `dt=1 s`.
W1 sampled compute energy is the per-seed target. W0 and W2–W5 must match it
within 0.1% (0.01% preferred); infeasible traces remain explicitly
`INVALID_ENERGY_MATCH` and are never silently clipped into validity.

## Workloads and allowed information

- W0 `constant_reference`: constant power equal to W1's measurement mean.
- W1 `diversified_stochastic`: canonical v0.4.4 `load_nominal`.
- W2 `bursty_benign`: synthetic bounded stochastic bursts; no orbital or
  thermal input.
- W3 `queue_driven_benign`: synthetic FIFO jobs and dispatch; no orbital or
  thermal input.
- W4 `power_aware_benign`: may observe only time, its explicit RNG, and the
  caller-supplied dimensionless electrical-availability signal in `[0,1]`.
  It cannot observe node/radiator temperatures, environmental heat flux, or
  the hot-phase thermal indicator.
- W5 `phase_shaped_candidate`: canonical v0.4.4 `load_phase_locked`; it uses the
  canonical hot-phase convention. It is an adversarial candidate, not a
  validated attack.

## Commands and outputs

```text
python verify_baseline_v044.py
python run_wrb_001.py
python compare_wrb_001_migration.py
python plot_wrb_001.py
python verify_wrb_001_reproducibility.py results/WRB-001 results/WRB-001/repro-check --output results/WRB-001/reproducibility.json
python -m pytest -q
```

The classification rule is exploratory: `ROBUST` requires a material shaped
candidate and at least two material benign workload families; `CONDITIONAL`
indicates narrower dependence; otherwise the label is `NOT_ROBUST`. These are
campaign labels, not hardware thresholds or safety certification.
