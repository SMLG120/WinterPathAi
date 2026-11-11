"""Edge cost model (architecture §5). All weights are seconds and ≥ 0.

``cost_s = base_walk_s + disruption_penalty_s + risk_penalty_s + unknown_penalty_s
          + preference_penalty_s``

Hard exclusions are *not* handled here — prohibited edges never reach the cost function
(see :mod:`winterpath_routing.filters`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Edge, Profile, RiskEstimate, RiskLevel


@dataclass(frozen=True, slots=True)
class CostConfig:
    walk_speed_mps: float = 1.3
    reduced_mobility_speed_mps: float = 0.9

    #: Penalty for segments whose risk is unknown, in seconds per 100 m (default ≈ +3.9 % of
    #: walking time at 1.3 m/s). Small and positive: unknown is never treated as zero risk, but it
    #: is not presented as high risk either.
    unknown_penalty_s_per_100m: float = 3.0

    #: Risk penalty as a fraction of base walking time, per level, only for model_estimate /
    #: simulated risk evidence.
    risk_penalty_factor: dict[RiskLevel, float] = field(
        default_factory=lambda: {
            RiskLevel.LOW: 0.0,
            RiskLevel.MODERATE: 0.15,
            RiskLevel.ELEVATED: 0.40,
            RiskLevel.HIGH: 1.00,
        }
    )

    #: Confirmed disruption that does not block passage (e.g. construction impact), per edge.
    confirmed_disruption_penalty_s: float = 45.0
    #: Confirmed passage-blocking permit whose activity at departure is unknown
    #: (``wp.closure_active_at`` = NULL), per edge. Larger than a passable disruption because the
    #: sidewalk may be blocked; not an exclusion because activity is not established.
    possible_closure_penalty_s: float = 120.0
    #: Unverified reports (311 aggregate / approved community) when avoid_unverified_reports, per
    #: edge.
    unverified_report_penalty_s: float = 20.0
    #: Soft preference: unlit segments (lit = False) cost this fraction of base time extra.
    unlit_penalty_factor: float = 0.05
    #: reduced_mobility: soft penalty for edges explicitly not step-free (steps etc.).
    reduced_mobility_not_step_free_penalty_s: float = 300.0
    #: reduced_mobility: penalty factor of base time when step_free is unknown.
    reduced_mobility_unknown_step_free_factor: float = 0.10

    #: Snapping: origin/destination must be within this distance of a routable edge.
    snap_max_m: float = 75.0
    #: Spatial-match tolerance between a hazard geometry and an edge, metres (EPSG:32188).
    closure_match_tolerance_m: float = 5.0
    report_match_tolerance_m: float = 15.0

    def speed_for(self, profile: Profile) -> float:
        if profile is Profile.REDUCED_MOBILITY:
            return self.reduced_mobility_speed_mps
        return self.walk_speed_mps

    def __post_init__(self) -> None:
        numeric = [
            self.walk_speed_mps,
            self.reduced_mobility_speed_mps,
            self.unknown_penalty_s_per_100m,
            self.confirmed_disruption_penalty_s,
            self.possible_closure_penalty_s,
            self.unverified_report_penalty_s,
            self.unlit_penalty_factor,
            self.reduced_mobility_not_step_free_penalty_s,
            self.reduced_mobility_unknown_step_free_factor,
            self.snap_max_m,
            self.closure_match_tolerance_m,
            self.report_match_tolerance_m,
            *self.risk_penalty_factor.values(),
        ]
        if any(v < 0 for v in numeric):
            raise ValueError("cost configuration values must be non-negative")
        if self.walk_speed_mps <= 0 or self.reduced_mobility_speed_mps <= 0:
            raise ValueError("walking speeds must be positive")
        if self.unknown_penalty_s_per_100m <= 0:
            raise ValueError("unknown_penalty_s_per_100m must be > 0 (unknown is never zero risk)")


@dataclass(frozen=True, slots=True)
class EdgeCost:
    base_s: float
    disruption_s: float = 0.0
    risk_s: float = 0.0
    unknown_s: float = 0.0
    preference_s: float = 0.0

    @property
    def total_s(self) -> float:
        return self.base_s + self.disruption_s + self.risk_s + self.unknown_s + self.preference_s


def edge_cost(
    edge: Edge,
    profile: Profile,
    risk: RiskEstimate,
    *,
    n_confirmed_disruptions: int,
    n_unverified_reports: int,
    avoid_unverified_reports: bool,
    config: CostConfig,
    n_possible_closures: int = 0,
) -> EdgeCost:
    base = edge.length_m / config.speed_for(profile)

    disruption = config.confirmed_disruption_penalty_s * (1 if n_confirmed_disruptions else 0)
    if n_possible_closures:
        disruption += config.possible_closure_penalty_s
    if avoid_unverified_reports and n_unverified_reports:
        disruption += config.unverified_report_penalty_s

    risk_s = 0.0
    unknown_s = 0.0
    if risk.is_unknown:
        unknown_s = config.unknown_penalty_s_per_100m * edge.length_m / 100.0
    else:
        risk_s = base * config.risk_penalty_factor.get(risk.level, 0.0)

    pref = 0.0
    if edge.lit is False:
        pref += base * config.unlit_penalty_factor
    if profile is Profile.REDUCED_MOBILITY:
        if edge.step_free is False or edge.edge_kind == "steps":
            pref += config.reduced_mobility_not_step_free_penalty_s
        elif edge.step_free is None:
            pref += base * config.reduced_mobility_unknown_step_free_factor

    return EdgeCost(base, disruption, risk_s, unknown_s, pref)
