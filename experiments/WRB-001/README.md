# WRB-001 — Paired-Seed Workload Robustness Campaign

WRB-001 characterizes workload-timing sensitivity in the reconstructed TSM-01
two-node model. It does not validate an attack, a vulnerability, or a deployed
orbital-compute architecture.

## Baseline boundary

The workspace supplied only the v0.4.4 DOCX, release notes, QA report, and
`results_v044.json`; the historical Python source and release manifest were not
available. The implementation therefore reconstructs the standard two-node
equations and parameters documented by v0.4.4. It preserves the four supplied
artefacts byte-for-byte and labels every new result as reconstructed.

The reconstructed equations are independently checked against the published
fixed-forcing convergence values. The stochastic W1 and W5 formulas cannot be
claimed byte-identical to their missing historical implementations.

## Pairing and RNG streams

Seeds 0–99 are authoritative. Each workload receives a stable child seed
derived from `(campaign, run seed, workload id)`, so changing workload execution
order cannot change a trace. The physical/environmental model is deterministic
and its realization hash is shared by all six workloads in every pair. No new
physical-parameter uncertainty is injected because that would change the frozen
model assumptions.

## Energy reference and interval

All comparisons use the half-open interval beginning after two complete warmup
orbits and spanning six complete measurement orbits. W1's sampled compute
energy for a seed is the pairing target; W0 and W2–W5 must match it within 0.1%
(with 0.01% preferred). An infeasible constrained trace is retained as
`INVALID_ENERGY_MATCH`; it is never silently clipped into validity.

W0 is the primary constant reference for `delta_peak_temperature_vs_reference_K`.
The campaign also records deltas versus W1 so the historical benign/shaped
comparison can be inspected without redefining the primary reference.

## Workloads and allowed information

- W0 `constant_reference`: constant power equal to W1's measured mean.
- W1 `diversified_stochastic`: transparent reconstruction of the documented
  synthetic diversified stochastic workload.
- W2 `bursty_benign`: stochastic arrivals and bounded bursts; no orbital or
  thermal input.
- W3 `queue_driven_benign`: synthetic jobs, backlog, service, and dispatch; no
  orbital or thermal input.
- W4 `power_aware_benign`: observes only an abstract electrical-power
  availability series and its own RNG. Its function does not accept node or
  radiator temperature, environmental heat flux, or the thermal hot indicator.
- W5 `phase_shaped_candidate`: may observe the documented orbital hot-phase
  indicator. It is an adversarial candidate, not a validated attack.

Electrical availability can remain correlated with orbital phase; W4 is
therefore described as non-thermal-input benign scheduling, not as causally
independent of the orbital environment.

## Run

```text
python run_wrb_001.py
python plot_wrb_001.py
python verify_wrb_001_reproducibility.py results/WRB-001 results/WRB-001/repro-check --output results/WRB-001/reproducibility.json
python -m pytest -q
```

Use `python run_wrb_001.py --seeds 0 1` for a short smoke test. Authoritative
outputs are `results/WRB-001/runs.csv`, `runs.jsonl`, and `summary.json`.

## Classification

The exploratory campaign rule calls a family material when its median absolute
paired peak-temperature delta is at least 1 K and its paired-seed percentile
bootstrap 95% interval excludes zero in the same direction. `ROBUST` requires
the shaped candidate and at least two benign families; `CONDITIONAL` indicates
more limited dependence; otherwise the result is `NOT_ROBUST`. These are
campaign labels, not safety-certification or hardware thresholds.
