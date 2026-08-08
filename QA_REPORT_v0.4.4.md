# OCTM / TSM-01 v0.4.4 - AI-Assisted Release QA Record

## Provenance

- Performed by: **GPT-5.6 Sol via ChatGPT tooling**, acting as an AI-assisted build/release QA system.
- Date: 8 August 2026.
- Independent human reviewer: **None**.
- Independent spacecraft-thermal reviewer: **None**.
- Interpretation boundary: this record covers build integrity, reproducibility checks, document rendering/accessibility and internal consistency. It is **not scientific peer review, spacecraft-thermal validation, certification, or organisational endorsement**.

## Scope and results

- `python -m py_compile thermal_model.py run_all_v044.py plot_results.py`: **PASS**.
- Authoritative campaign deterministic re-run: **PASS**. `results_v044.json` reproduced with SHA-256 `51ee15fc35b2494123b9bb10141ce2eeacbc54d2f1a0c4170920abaa66430686` in the recorded environment.
- Deterministic integration-convergence experiment: **PASS as a fixed-forcing numerical check**. The stochastic release-step/realisation sensitivity is reported separately and is not labelled convergence.
- Figure regeneration: **PASS**. All five figures regenerated from v0.4.4 results and were byte-identical to the five corresponding images embedded in the final DOCX in the recorded environment.
- DOCX render: **PASS**. Final document rendered to **23 pages** with the canonical DOCX renderer; every rendered page was visually inspected by the AI-assisted QA process for clipping, overlap, broken tables, missing glyphs and header/footer defects.
- DOCX accessibility audit: **PASS - 0 high / 0 medium / 0 low findings** after marking the remaining table header row.
- Release manifest: **verified after final packaging**; `MANIFEST.sha256` covers all authoritative release artefacts except itself.
- Legacy normative numerical scripts: **excluded** from the v0.4.4 release package.

## QA limitations

- Visual inspection by an AI system is not equivalent to independent human editorial review.
- Hash equality establishes file identity, not scientific correctness.
- Deterministic reruns establish reproducibility under the recorded implementation and dependency environment, not model validity.
- The two-node model form and Appendix A physical parameters remain pending independent spacecraft-thermal review.
