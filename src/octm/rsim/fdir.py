"""RSIM canonical-derived monotone FDIR controller."""

from __future__ import annotations

from dataclasses import dataclass
import math


CONTROLLER_LABEL = "RSIM canonical-derived monotone FDIR"


@dataclass(frozen=True, slots=True)
class FDIRParameters:
    threshold_K: float = 348.15
    hysteresis_K: float = 5.0
    latency_s: float = 30.0
    shedding_limit_W: float = 12_000.0

    def validate(self) -> None:
        values = (self.threshold_K, self.hysteresis_K, self.latency_s, self.shedding_limit_W)
        if any(not math.isfinite(v) or v < 0.0 for v in values):
            raise ValueError("FDIR parameters must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class FDIRState:
    armed_at_s: float | None = None
    shedding: bool = False


@dataclass(frozen=True, slots=True)
class FDIRDecision:
    state: FDIRState
    power_limit_W: float
    activated: bool
    recovered: bool
    label: str = CONTROLLER_LABEL


def fdir_decision(
    *,
    node_temperature_K: float,
    time_s: float,
    requested_compute_W: float,
    state: FDIRState,
    enabled: bool,
    params: FDIRParameters,
) -> FDIRDecision:
    """Apply canonical arming/recovery timing with a monotone power limit."""

    params.validate()
    if any(not math.isfinite(v) for v in (node_temperature_K, time_s, requested_compute_W)):
        raise ValueError("FDIR inputs must be finite")
    if requested_compute_W < 0.0:
        raise ValueError("requested compute power must be non-negative")
    if not enabled:
        return FDIRDecision(FDIRState(), math.inf, False, False)

    armed_at = state.armed_at_s
    shedding = state.shedding
    was_shedding = shedding
    recovered = False
    if node_temperature_K >= params.threshold_K:
        if armed_at is None:
            armed_at = time_s
        if (not shedding) and time_s - armed_at >= params.latency_s:
            shedding = True
    elif node_temperature_K < params.threshold_K - params.hysteresis_K:
        recovered = armed_at is not None or shedding
        shedding = False
        armed_at = None
    activated = shedding and not was_shedding
    limit = params.shedding_limit_W if shedding else math.inf
    # The controller returns a limit, never an absolute replacement command.
    assert min(requested_compute_W, limit) <= requested_compute_W
    return FDIRDecision(FDIRState(armed_at, shedding), limit, activated, recovered)


__all__ = [
    "CONTROLLER_LABEL", "FDIRDecision", "FDIRParameters", "FDIRState", "fdir_decision",
]
