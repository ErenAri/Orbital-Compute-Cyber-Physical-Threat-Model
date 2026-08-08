# Historical TSM-01 reconstruction validation record

At the time of this earlier validation, the v0.4.4 Python source was not present.
The thermal plant was reconstructed from Appendix A and the documented
two-node heat-balance description without altering the four retained release
artefacts.

At `dt=1 s`, the reconstructed fixed-forcing check produces:

- flat 30 kW peak: `50.986481429 °C`;
- deterministic phase-shaped peak: `68.439836841 °C`;
- paired difference: `17.453355412 K`.

The corresponding rounded v0.4.4 values are `50.986481 °C`, `68.439837 °C`,
and `17.453355 K`. The remaining published fixed-forcing steps from 0.125 s
through 4 s are reproduced within `4.75e-7 K` of the rounded JSON values.

This validated the reconstructed thermal equations, parameters, phase
convention, and integration ordering against the retained deterministic
evidence. The canonical historical source is now retained under
`src/octm/baselines/v044/` and supersedes this reconstruction. This record is
retained only for provenance and is not independent spacecraft-thermal review.
