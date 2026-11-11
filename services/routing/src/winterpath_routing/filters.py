"""Hard exclusions. Excluded edges are removed from the search, never penalised."""

from __future__ import annotations

from collections.abc import Collection
from enum import StrEnum

from .models import Edge, Profile


class ExclusionReason(StrEnum):
    NO_FOOT_ACCESS = "NO_FOOT_ACCESS"
    CONFIRMED_CLOSURE = "CONFIRMED_CLOSURE"
    NOT_VERIFIED_STEP_FREE = "NOT_VERIFIED_STEP_FREE"
    OUTSIDE_MAIN_COMPONENT = "OUTSIDE_MAIN_COMPONENT"


def exclusion_reason(
    edge: Edge,
    profile: Profile,
    *,
    closed_edge_ids: Collection[str] = (),
    main_component_edge_ids: Collection[str] | None = None,
) -> ExclusionReason | None:
    if not edge.foot_legal:
        return ExclusionReason.NO_FOOT_ACCESS
    if edge.edge_id in closed_edge_ids:
        return ExclusionReason.CONFIRMED_CLOSURE
    # step_free is a HARD constraint: only edges verified step-free (True) are allowed.
    if profile is Profile.STEP_FREE and edge.step_free is not True:
        return ExclusionReason.NOT_VERIFIED_STEP_FREE
    if main_component_edge_ids is not None and edge.edge_id not in main_component_edge_ids:
        return ExclusionReason.OUTSIDE_MAIN_COMPONENT
    return None
