import json
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.permissions import require_roles, UserContext, Role
from app.database.dependencies import get_db
from app.database.transaction import transaction_scope
from app.schemas.blackout import (
    BlackoutConflictPreview,
    BlackoutCreate,
    BlackoutResponse,
)
from app.services.audit_service import log_system_audit
from app.services.blackout_service import (
    conflict_payload,
    campus_datetime,
    campus_now_naive,
    expand_weekday_occurrences,
    find_booking_conflicts,
    normalize_selection_times,
    notify_other_admins_of_conflicts,
    notify_users_of_confirmed_blackout_conflicts,
    resolve_resources,
    store_category_ids,
    store_resource_ids,
)

router = APIRouter()


BLACKOUT_SELECT = """
    SELECT bo.blackout_id, bo.resource_id, bo.maintenance_id, bo.blackout_group_id,
           bo.start_datetime, bo.end_datetime, bo.reason, bo.reason_category,
           bo.reason_explanation, bo.category_ids, bo.excluded_resource_ids, bo.status, bo.created_by,
           bo.cancelled_by, bo.cancelled_at, bo.created_at,
           r.resource_name, r.category_id, c.category_name, u.name AS creator_name
    FROM resource_blackout_periods bo
    JOIN resources r ON bo.resource_id = r.resource_id
    JOIN categories c ON r.category_id = c.category_id
    JOIN users u ON bo.created_by = u.user_id
"""


def _decode_category_ids(value) -> List[int]:
    if not value:
        return []
    if isinstance(value, list):
        return [int(item) for item in value]
    try:
        return [int(item) for item in json.loads(value)]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _blackout_response(row) -> BlackoutResponse:
    blackout_status = row["status"]
    if blackout_status == "Cancelled":
        window_state = "Cancelled"
    elif row["end_datetime"] <= campus_now_naive():
        window_state = "Expired"
    elif row["start_datetime"] > campus_now_naive():
        window_state = "Upcoming"
    else:
        window_state = "Active"
    return BlackoutResponse(
        blackout_id=row["blackout_id"],
        resource_id=row["resource_id"],
        resource_name=row["resource_name"],
        category_id=row.get("category_id"),
        category_name=row.get("category_name"),
        maintenance_id=row["maintenance_id"],
        blackout_group_id=row["blackout_group_id"],
        start_datetime=row["start_datetime"],
        end_datetime=row["end_datetime"],
        reason=row["reason"],
        reason_category=row["reason_category"] or "Other",
        reason_explanation=row["reason_explanation"] or row["reason"],
        category_ids=_decode_category_ids(row["category_ids"]),
        excluded_resource_ids=_decode_category_ids(row["excluded_resource_ids"]),
        status=row["status"],
        window_state=window_state,
        created_by=row["created_by"],
        creator_name=row["creator_name"],
        cancelled_by=row["cancelled_by"],
        cancelled_at=row["cancelled_at"],
        created_at=row["created_at"],
    )


def _get_group_rows(cursor, blackout_id: int):
    cursor.execute(
        """
        SELECT blackout_id, resource_id, maintenance_id, blackout_group_id,
               start_datetime, end_datetime, reason, reason_category,
               reason_explanation, category_ids, excluded_resource_ids, status, created_by,
               cancelled_by, cancelled_at, created_at
        FROM resource_blackout_periods
        WHERE blackout_id = %s
        """,
        (blackout_id,),
    )
    blackout = cursor.fetchone()
    if not blackout:
        raise HTTPException(status_code=404, detail="Blackout record not found.")
    if blackout["blackout_group_id"]:
        cursor.execute(
            """
            SELECT blackout_id, resource_id, maintenance_id, blackout_group_id,
                   start_datetime, end_datetime, reason, reason_category,
                   reason_explanation, category_ids, excluded_resource_ids, status, created_by,
                   cancelled_by, cancelled_at, created_at
            FROM resource_blackout_periods
            WHERE blackout_group_id = %s AND status = 'Active'
            ORDER BY resource_id
            """,
            (blackout["blackout_group_id"],),
        )
        return blackout, cursor.fetchall()
    return blackout, [blackout]


def _conflict_detail(conflicts):
    return {
        "message": (
            f"The blackout overlaps {len(conflicts)} existing "
            "pending or approved booking(s) overlap the selected resources. "
            "Review the bookings and explicitly confirm to proceed without cancelling them."
        ),
        "confirmation_required": True,
        "conflicts": conflict_payload(conflicts),
    }


@router.get("", response_model=List[BlackoutResponse], summary="List resource blackout periods (Admin/Staff)")
@router.get("/", response_model=List[BlackoutResponse], include_in_schema=False)
def list_blackouts(
    resource_id: Optional[int] = Query(None, ge=1),
    category_id: Optional[int] = Query(None, ge=1),
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(Active|Cancelled)$"),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: UserContext = Depends(require_roles(Role.ADMIN, Role.STAFF)),
    db=Depends(get_db),
):
    if start_date and end_date and campus_datetime(start_date) > campus_datetime(end_date):
        raise HTTPException(status_code=422, detail="Filter start date must be on or before its end date.")
    query = BLACKOUT_SELECT + " WHERE 1=1"
    params = []
    if resource_id:
        query += " AND bo.resource_id = %s"
        params.append(resource_id)
    if category_id:
        query += " AND r.category_id = %s"
        params.append(category_id)
    if status_filter:
        query += " AND bo.status = %s"
        params.append(status_filter)
    if start_date:
        query += " AND bo.end_datetime >= %s"
        params.append(campus_datetime(start_date))
    if end_date:
        query += " AND bo.start_datetime < %s"
        params.append(campus_datetime(end_date))
    query += " ORDER BY bo.start_datetime DESC, bo.blackout_id DESC"
    db.execute(query, tuple(params))
    return [_blackout_response(row) for row in db.fetchall()]


@router.post("/conflicts", summary="Preview bookings that conflict with a proposed blackout")
def preview_blackout_conflicts(
    req: BlackoutConflictPreview,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
):
    start, end = normalize_selection_times(req)
    occurrences = expand_weekday_occurrences(start, end, req.repeat_weekdays)
    with transaction_scope() as (conn, cursor):
        resources = resolve_resources(
            cursor, req.resource_ids, req.category_ids, req.excluded_resource_ids
        )
        conflicts = []
        for occurrence_start, occurrence_end in occurrences:
            occurrence_conflicts = find_booking_conflicts(
                cursor, [row["resource_id"] for row in resources], occurrence_start, occurrence_end
            )
            for conflict in occurrence_conflicts:
                conflicts.append({
                    **conflict,
                    "blackout_start_datetime": occurrence_start,
                    "blackout_end_datetime": occurrence_end,
                })
            if occurrence_conflicts:
                notify_other_admins_of_conflicts(
                    cursor, current_user.user_id, occurrence_conflicts, occurrence_start, occurrence_end
                )
    return {
        "resource_count": len(resources),
        "occurrence_count": len(occurrences),
        "repeat_weekdays": req.repeat_weekdays,
        "resources": [
            {
                "resource_id": row["resource_id"],
                "resource_name": row["resource_name"],
                "category_id": row["category_id"],
                "category_name": row["category_name"],
            }
            for row in resources
        ],
        "conflict_count": len(conflicts),
        "conflicts": conflict_payload(conflicts),
    }


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create resource blackout(s) atomically (Admin)")
def create_blackout(
    req: BlackoutCreate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
):
    start, end = normalize_selection_times(req)
    if end <= start:
        raise HTTPException(status_code=422, detail="End datetime must be after start datetime.")
    occurrences = expand_weekday_occurrences(start, end, req.repeat_weekdays)
    group_ids = []
    conflict_rows = []
    blackout_ids = []
    selected_resources = []
    created_at = None
    reason = req.reason_explanation.strip()
    categories_json = store_category_ids(req.category_ids)
    exclusions_json = store_resource_ids(req.excluded_resource_ids)

    with transaction_scope() as (conn, cursor):
        selected_resources = resolve_resources(
            cursor, req.resource_ids, req.category_ids, req.excluded_resource_ids, lock=True
        )
        resource_ids = [row["resource_id"] for row in selected_resources]
        for occurrence_start, occurrence_end in occurrences:
            occurrence_conflicts = find_booking_conflicts(
                cursor, resource_ids, occurrence_start, occurrence_end, locking_read=True
            )
            for conflict in occurrence_conflicts:
                conflict_rows.append({
                    **conflict,
                    "blackout_start_datetime": occurrence_start,
                    "blackout_end_datetime": occurrence_end,
                })
            if occurrence_conflicts:
                notify_other_admins_of_conflicts(
                    cursor, current_user.user_id, occurrence_conflicts, occurrence_start, occurrence_end
                )
            if req.confirm_booking_conflicts:
                notify_users_of_confirmed_blackout_conflicts(
                    cursor, occurrence_conflicts, occurrence_start, occurrence_end, reason
                )
        if not conflict_rows or req.confirm_booking_conflicts:
            group_id = str(uuid.uuid4())
            group_ids.append(group_id)
            for occurrence_start, occurrence_end in occurrences:
                for resource in selected_resources:
                    cursor.execute(
                        """
                        INSERT INTO resource_blackout_periods (
                            resource_id, maintenance_id, blackout_group_id,
                            start_datetime, end_datetime, reason, reason_category,
                            reason_explanation, category_ids, excluded_resource_ids, status, created_by
                        )
                        VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, 'Active', %s)
                        """,
                        (
                            resource["resource_id"],
                            group_id,
                            occurrence_start,
                            occurrence_end,
                            reason[:255],
                            req.reason_category,
                            reason,
                            categories_json,
                            exclusions_json,
                            current_user.user_id,
                        ),
                    )
                    blackout_id = cursor.lastrowid
                    blackout_ids.append(blackout_id)
                    if created_at is None:
                        cursor.execute(
                            "SELECT created_at FROM resource_blackout_periods WHERE blackout_id = %s",
                            (blackout_id,),
                        )
                        created_at = cursor.fetchone()["created_at"]
                    log_system_audit(
                        cursor,
                        entity_type="Blackout",
                        entity_id=blackout_id,
                        action="Created",
                        changed_by=current_user.user_id,
                        old_values=None,
                        new_values={
                            "resource_id": resource["resource_id"],
                            "blackout_group_id": group_id,
                            "category_ids": req.category_ids,
                            "start_datetime": occurrence_start.isoformat(),
                            "end_datetime": occurrence_end.isoformat(),
                            "repeat_weekdays": req.repeat_weekdays,
                            "reason_category": req.reason_category,
                            "reason_explanation": reason,
                        },
                        remarks=f"Blackout scheduled by {current_user.name}",
                    )

    if conflict_rows and not req.confirm_booking_conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_conflict_detail(conflict_rows),
        )

    first_start, first_end = occurrences[0]
    now = campus_now_naive()
    window_state = "Expired" if first_end <= now else "Upcoming" if first_start > now else "Active"
    return {
        "blackout_id": blackout_ids[0],
        "resource_id": selected_resources[0]["resource_id"],
        "resource_name": selected_resources[0]["resource_name"],
        "maintenance_id": None,
        "blackout_ids": blackout_ids,
        "blackout_group_id": group_ids[0],
        "occurrence_count": len(occurrences),
        "resource_count": len(selected_resources),
        "resource_names": [row["resource_name"] for row in selected_resources],
        "category_id": selected_resources[0]["category_id"],
        "category_name": selected_resources[0]["category_name"],
        "start_datetime": first_start,
        "end_datetime": first_end,
        "reason": reason[:255],
        "reason_category": req.reason_category,
        "reason_explanation": reason,
        "category_ids": req.category_ids,
        "excluded_resource_ids": req.excluded_resource_ids,
        "status": "Active",
        "window_state": window_state,
        "created_by": current_user.user_id,
        "creator_name": current_user.name,
        "created_at": created_at,
    }


@router.put("/{blackout_id:int}", summary="Edit a blackout window or its bulk group (Admin)")
def update_blackout(
    blackout_id: int,
    req: BlackoutCreate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
):
    start, end = normalize_selection_times(req)
    if end <= start:
        raise HTTPException(status_code=422, detail="End datetime must be after start datetime.")
    conflict_rows = []
    affected_ids = []
    reason = req.reason_explanation.strip()

    with transaction_scope() as (conn, cursor):
        blackout, group_rows = _get_group_rows(cursor, blackout_id)
        if blackout["maintenance_id"] is not None:
            raise HTTPException(status_code=409, detail="Maintenance-linked blackouts must be changed through Maintenance.")
        if blackout["status"] != "Active":
            raise HTTPException(status_code=409, detail="Only active blackout windows can be edited.")
        if any(row["status"] != "Active" for row in group_rows):
            raise HTTPException(status_code=409, detail="Only active blackout windows can be edited.")

        old_resource_ids = sorted({row["resource_id"] for row in group_rows})
        proposed_resources = resolve_resources(
            cursor, req.resource_ids, req.category_ids, req.excluded_resource_ids
        )
        new_resource_ids = sorted({row["resource_id"] for row in proposed_resources})
        lock_ids = sorted(set(old_resource_ids + new_resource_ids))
        cursor.execute(
            f"SELECT resource_id FROM resources WHERE resource_id IN ({','.join(['%s'] * len(lock_ids))}) ORDER BY resource_id FOR UPDATE",
            tuple(lock_ids),
        )
        locked_ids = {row["resource_id"] for row in cursor.fetchall()}
        if locked_ids != set(lock_ids):
            raise HTTPException(status_code=404, detail="One or more selected resources no longer exist.")
        resources = resolve_resources(
            cursor, req.resource_ids, req.category_ids, req.excluded_resource_ids
        )
        conflict_rows = find_booking_conflicts(
            cursor,
            [row["resource_id"] for row in resources],
            start,
            end,
            locking_read=True,
        )
        if conflict_rows:
            notify_other_admins_of_conflicts(cursor, current_user.user_id, conflict_rows, start, end)
            if req.confirm_booking_conflicts:
                notify_users_of_confirmed_blackout_conflicts(
                    cursor, conflict_rows, start, end, reason
                )
        if not conflict_rows or req.confirm_booking_conflicts:
            group_id = blackout["blackout_group_id"] or str(uuid.uuid4())
            category_json = store_category_ids(req.category_ids)
            exclusions_json = store_resource_ids(req.excluded_resource_ids)
            existing_by_resource = {row["resource_id"]: row for row in group_rows}
            new_ids = {row["resource_id"] for row in resources}
            removed_rows = [
                row for row in group_rows
                if row["resource_id"] not in new_ids and row["status"] == "Active"
            ]
            for removed in removed_rows:
                cursor.execute(
                    """
                    UPDATE resource_blackout_periods
                    SET status = 'Cancelled', cancelled_by = %s, cancelled_at = %s
                    WHERE blackout_id = %s AND status = 'Active'
                    """,
                    (current_user.user_id, campus_now_naive(), removed["blackout_id"]),
                )
                log_system_audit(
                    cursor,
                    entity_type="Blackout",
                    entity_id=removed["blackout_id"],
                    action="Cancelled",
                    changed_by=current_user.user_id,
                    old_values={"resource_id": removed["resource_id"], "status": "Active"},
                    new_values={"status": "Cancelled", "reason": "Resource removed during blackout edit"},
                    remarks=f"Blackout resource selection updated by {current_user.name}",
                )

            for resource in resources:
                existing = existing_by_resource.get(resource["resource_id"])
                if existing and existing["status"] == "Active":
                    new_id = existing["blackout_id"]
                    cursor.execute(
                        """
                        UPDATE resource_blackout_periods
                        SET blackout_group_id = %s, start_datetime = %s, end_datetime = %s,
                            reason = %s, reason_category = %s, reason_explanation = %s,
                            category_ids = %s, excluded_resource_ids = %s
                        WHERE blackout_id = %s AND status = 'Active'
                        """,
                        (
                            group_id, start, end, reason[:255], req.reason_category,
                            reason, category_json, exclusions_json, new_id,
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO resource_blackout_periods (
                            resource_id, maintenance_id, blackout_group_id,
                            start_datetime, end_datetime, reason, reason_category,
                            reason_explanation, category_ids, excluded_resource_ids, status, created_by
                        )
                        VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, 'Active', %s)
                        """,
                        (
                            resource["resource_id"], group_id, start, end, reason[:255],
                            req.reason_category, reason, category_json, exclusions_json, current_user.user_id,
                        ),
                    )
                    new_id = cursor.lastrowid
                affected_ids.append(new_id)
                log_system_audit(
                    cursor,
                    entity_type="Blackout",
                    entity_id=new_id,
                    action="Updated",
                    changed_by=current_user.user_id,
                    old_values={
                        "blackout_group_id": blackout["blackout_group_id"],
                        "resource_ids": old_resource_ids,
                    },
                    new_values={
                        "blackout_group_id": group_id,
                        "resource_ids": [row["resource_id"] for row in resources],
                        "start_datetime": start.isoformat(),
                        "end_datetime": end.isoformat(),
                        "reason_category": req.reason_category,
                        "reason_explanation": reason,
                    },
                    remarks=f"Blackout updated by {current_user.name}",
                )

    if conflict_rows and not req.confirm_booking_conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_conflict_detail(conflict_rows),
        )
    return {
        "message": "Blackout window updated.",
        "blackout_ids": affected_ids,
        "resource_count": len(affected_ids),
    }


@router.patch("/{blackout_id:int}/cancel", summary="Cancel blackout and preserve its history (Admin)")
def cancel_blackout(
    blackout_id: int,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
):
    with transaction_scope() as (conn, cursor):
        blackout, group_rows = _get_group_rows(cursor, blackout_id)
        if blackout["maintenance_id"] is not None:
            raise HTTPException(status_code=409, detail="Maintenance-linked blackouts must be changed through Maintenance.")
        active_ids = [row["blackout_id"] for row in group_rows if row["status"] == "Active"]
        if not active_ids:
            raise HTTPException(status_code=409, detail="This blackout has already been cancelled.")

        resource_ids = sorted({row["resource_id"] for row in group_rows if row["blackout_id"] in active_ids})
        cursor.execute(
            f"SELECT resource_id FROM resources WHERE resource_id IN ({','.join(['%s'] * len(resource_ids))}) ORDER BY resource_id FOR UPDATE",
            tuple(resource_ids),
        )
        cursor.fetchall()
        cursor.execute(
            f"""
            UPDATE resource_blackout_periods
            SET status = 'Cancelled', cancelled_by = %s, cancelled_at = %s
            WHERE blackout_id IN ({','.join(['%s'] * len(active_ids))})
              AND status = 'Active'
            """,
            tuple([current_user.user_id, campus_now_naive(), *active_ids]),
        )
        for row in group_rows:
            if row["blackout_id"] not in active_ids:
                continue
            log_system_audit(
                cursor,
                entity_type="Blackout",
                entity_id=row["blackout_id"],
                action="Cancelled",
                changed_by=current_user.user_id,
                old_values={"status": "Active", "reason": row["reason"]},
                new_values={"status": "Cancelled"},
                remarks=f"Blackout cancelled by {current_user.name}",
            )
    return {"message": "Blackout cancelled; its history was retained.", "cancelled_count": len(active_ids)}


@router.delete("/{blackout_id:int}", summary="Delete a blackout period (Admin)")
def delete_blackout(
    blackout_id: int,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
):
    return cancel_blackout(blackout_id, current_user)
