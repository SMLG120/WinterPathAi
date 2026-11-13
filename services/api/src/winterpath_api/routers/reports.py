"""Community reports + admin moderation."""

from __future__ import annotations

import hmac
import secrets
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Header, Query, Request, Response

from ..deps import get_state, require_public_writes
from ..errors import ApiError
from ..params import decode_cursor, encode_cursor, in_coverage
from ..repositories.reports import StoredReport
from ..schemas import (
    ModerationDecision,
    ModerationStatus,
    ReportAdminList,
    ReportAdminView,
    ReportCreate,
    ReportReceipt,
)
from ..security import check_admin, sha256_hex
from ..state import AppState

router = APIRouter()
log = structlog.get_logger("winterpath_api.reports")


def _not_found() -> ApiError:
    return ApiError(404, "NOT_FOUND", "Report not found.")


def _parse_uuid(raw: str) -> uuid.UUID:
    """Admin endpoints: malformed id → 422 (declared since contract v1.1.0)."""
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise ApiError(422, "VALIDATION_ERROR", "reportId must be a UUID.") from exc


def admin_view(r: StoredReport) -> dict:
    return {
        "id": r.id,
        "category": r.category,
        "location": {"lon": r.lon, "lat": r.lat},
        "description": r.description,
        "status": r.status,
        "created_at": r.created_at,
        "expires_at": r.expires_at,
        "moderated_at": r.moderated_at,
        "moderation_note": r.moderation_note,
    }


@router.post(
    "/reports",
    status_code=201,
    response_model=ReportReceipt,
    tags=["reports"],
    dependencies=[Depends(require_public_writes)],
)
def create_report(
    body: ReportCreate, request: Request, state: AppState = Depends(get_state)
) -> ReportReceipt:
    client = state.client_hash(request)
    state.limiter.check("reports", client, min(10, state.settings.rate_limit_per_minute))
    if not in_coverage(body.location.lon, body.location.lat, state.coverage_bbox):
        raise ApiError(
            422,
            "OUTSIDE_COVERAGE",
            "Report location is outside the coverage area.",
            {"coverage_bbox": list(state.coverage_bbox)},
        )
    token = secrets.token_urlsafe(32)  # 43 chars; only its hash is stored
    r = state.reports.create(
        category=body.category,
        lon=body.location.lon,
        lat=body.location.lat,
        description=body.description,
        deletion_token_hash=sha256_hex(token),
        client_hash=client,
        now=datetime.now(UTC),
    )
    log.info("report_created", category=r.category, location=[r.lon, r.lat])
    return ReportReceipt(id=r.id, status=r.status, expires_at=r.expires_at, deletion_token=token)


@router.delete("/reports/{reportId}", status_code=204, tags=["reports"])
def delete_own_report(
    reportId: str,
    x_deletion_token: str | None = Header(None, alias="X-Deletion-Token"),
    state: AppState = Depends(get_state),
) -> Response:
    # Contract v1.5 (CR-ROUTING-4): a wrong, missing or malformed token, or an unknown/non-UUID
    # id, is 404 NOT_FOUND — the response never reveals whether a report exists.
    try:
        rid = uuid.UUID(reportId)
    except ValueError:
        raise _not_found() from None
    if not x_deletion_token or not 32 <= len(x_deletion_token) <= 128:
        raise _not_found()
    now = datetime.now(UTC)
    r = state.reports.get(rid, now)
    if r is None or r.status == "deleted":
        raise _not_found()
    if not hmac.compare_digest(sha256_hex(x_deletion_token), r.deletion_token_hash):
        raise _not_found()
    if not state.reports.delete_own(rid, now):
        raise _not_found()
    return Response(status_code=204)


def require_admin(request: Request, state: AppState = Depends(get_state)) -> None:
    check_admin(request, state.settings.admin_token_hash)


@router.get(
    "/admin/reports",
    response_model=ReportAdminList,
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)
def list_reports_for_moderation(
    status: ModerationStatus | None = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    cursor: str | None = Query(None),
    state: AppState = Depends(get_state),
) -> ReportAdminList:
    c = decode_cursor(cursor)
    after = None
    if c:
        try:
            after = (datetime.fromisoformat(c["ts"]), uuid.UUID(c["id"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise ApiError(400, "VALIDATION_ERROR", "Invalid pagination cursor.") from exc
    rows = state.reports.list(status, limit + 1, after, datetime.now(UTC))
    page = rows[:limit]
    nxt = (
        encode_cursor({"ts": page[-1].created_at.isoformat(), "id": str(page[-1].id)})
        if len(rows) > limit
        else None
    )
    return ReportAdminList.model_validate(
        {"items": [admin_view(r) for r in page], "next_cursor": nxt}
    )


@router.post(
    "/admin/reports/{reportId}/moderation",
    response_model=ReportAdminView,
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)
def moderate_report(
    reportId: str,
    body: ModerationDecision,
    state: AppState = Depends(get_state),
) -> ReportAdminView:
    rid = _parse_uuid(reportId)
    r = state.reports.moderate(rid, body.decision, body.note, datetime.now(UTC))
    if r is None:
        raise _not_found()
    log.info("report_moderated", decision=body.decision, status=r.status)
    return ReportAdminView.model_validate(admin_view(r))
