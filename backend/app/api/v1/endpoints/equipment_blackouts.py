import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.permissions import require_roles, UserContext, Role
from app.database.dependencies import get_db
from app.database.transaction import transaction_scope
from app.schemas.blackout import (
    EquipmentBlackoutConflictPreview,
    EquipmentBlackoutCreate,
    EquipmentBlackoutResponse,
)
from app.services.audit_service import log_system_audit
from app.services.blackout_service import (
    campus_now_naive,
    expand_weekday_occurrences,
    normalize_selection_times,
)
from app.services.equipment_blackout_service import (
    find_equipment_booking_conflicts,
    notify_admins_of_equipment_blackout_conflicts,
    notify_users_of_confirmed_equipment_blackout_conflicts,
)

router = APIRouter()


def _resolve_equipment_items(cursor, item_ids, lock=False):
    item_ids = sorted(set(item_ids))
    if not item_ids:
        raise HTTPException(status_code=422, detail="Select at least one equipment item.")
    cursor.execute(
        f"""
        SELECT item_id, item_name, category, is_active
        FROM equipment_items
        WHERE item_id IN ({','.join(['%s'] * len(item_ids))})
        ORDER BY item_id
        {"FOR UPDATE" if lock else ""}
        """,
        tuple(item_ids),
    )
    items = cursor.fetchall()
    found = {row["item_id"] for row in items}
    missing = sorted(set(item_ids) - found)
    if missing:
        raise HTTPException(status_code=404, detail=f"Equipment items not found: {missing}.")
    inactive = [row["item_name"] for row in items if not row["is_active"]]
    if inactive:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Equipment must be active to schedule a blackout: {', '.join(inactive)}.",
        )
    return items


def _equipment_conflict_payload(conflicts, start_datetime, end_datetime):
    return [
        {
            "booking_id": row["booking_id"],
            "resource_id": row["item_id"],
            "resource_name": row["item_name"],
            "requester_name": row["requester_name"],
            "start_time": row["start_time"].isoformat(),
            "end_time": row["end_time"].isoformat(),
            "status": row["booking_status"],
            "purpose": row["purpose"],
            "quantity": row["requested_quantity"],
            "blackout_start_datetime": start_datetime.isoformat(),
            "blackout_end_datetime": end_datetime.isoformat(),
        }
        for row in conflicts
    ]


@router.get("", response_model=List[EquipmentBlackoutResponse])
@router.get("/", response_model=List[EquipmentBlackoutResponse], include_in_schema=False)
def list_equipment_blackouts(
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(Active|Cancelled)$"),
    current_user: UserContext = Depends(require_roles(Role.ADMIN, Role.STAFF)),
    db=Depends(get_db),
):
    query = """
        SELECT eb.equipment_blackout_id, eb.item_id, eb.blackout_group_id,
               eb.start_datetime, eb.end_datetime, eb.reason_category, eb.reason_explanation,
               eb.status, eb.created_by, eb.created_at, ei.item_name, ei.category,
               u.name AS creator_name
        FROM equipment_blackout_periods eb
        JOIN equipment_items ei ON ei.item_id = eb.item_id
        LEFT JOIN users u ON u.user_id = eb.created_by
        WHERE 1=1
    """
    params = []
    if status_filter:
        query += " AND eb.status = %s"
        params.append(status_filter)
    query += " ORDER BY eb.start_datetime DESC, eb.equipment_blackout_id DESC"
    db.execute(query, tuple(params))
    now = campus_now_naive()
    result = []
    for row in db.fetchall():
        if row["status"] == "Cancelled":
            state = "Cancelled"
        elif row["end_datetime"] <= now:
            state = "Expired"
        elif row["start_datetime"] > now:
            state = "Upcoming"
        else:
            state = "Active"
        result.append({**row, "window_state": state})
    return result


@router.post("/conflicts", summary="Preview bookings that conflict with an equipment blackout")
def preview_equipment_blackout_conflicts(
    req: EquipmentBlackoutConflictPreview,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
):
    start, end = normalize_selection_times(req)
    occurrences = expand_weekday_occurrences(start, end, req.repeat_weekdays)
    with transaction_scope() as (conn, cursor):
        items = _resolve_equipment_items(cursor, req.equipment_ids)
        conflicts = []
        for occurrence_start, occurrence_end in occurrences:
            occurrence_conflicts = find_equipment_booking_conflicts(
                cursor, req.equipment_ids, occurrence_start, occurrence_end
            )
            conflicts.extend(
                _equipment_conflict_payload(occurrence_conflicts, occurrence_start, occurrence_end)
            )
            notify_admins_of_equipment_blackout_conflicts(
                cursor, current_user.user_id, occurrence_conflicts, occurrence_start, occurrence_end
            )
    return {
        "equipment_count": len(items),
        "resource_count": len(items),
        "occurrence_count": len(occurrences),
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create equipment blackout periods atomically")
@router.post("/", status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_equipment_blackout(
    req: EquipmentBlackoutCreate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
):
    start, end = normalize_selection_times(req)
    occurrences = expand_weekday_occurrences(start, end, req.repeat_weekdays)
    conflicts = []
    blackout_ids = []
    group_ids = []
    created_at = None
    reason = req.reason_explanation.strip()

    with transaction_scope() as (conn, cursor):
        items = _resolve_equipment_items(cursor, req.equipment_ids, lock=True)
        item_ids = [item["item_id"] for item in items]
        for occurrence_start, occurrence_end in occurrences:
            occurrence_conflicts = find_equipment_booking_conflicts(
                cursor, item_ids, occurrence_start, occurrence_end, locking_read=True
            )
            conflicts.extend(
                _equipment_conflict_payload(occurrence_conflicts, occurrence_start, occurrence_end)
            )
            notify_admins_of_equipment_blackout_conflicts(
                cursor, current_user.user_id, occurrence_conflicts, occurrence_start, occurrence_end
            )
            if req.confirm_booking_conflicts:
                notify_users_of_confirmed_equipment_blackout_conflicts(
                    cursor, occurrence_conflicts, occurrence_start, occurrence_end, reason
                )

        if not conflicts or req.confirm_booking_conflicts:
            for occurrence_start, occurrence_end in occurrences:
                group_id = str(uuid.uuid4())
                group_ids.append(group_id)
                for item in items:
                    cursor.execute(
                        """
                        INSERT INTO equipment_blackout_periods (
                            item_id, blackout_group_id, start_datetime, end_datetime,
                            reason_category, reason_explanation, status, created_by
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, 'Active', %s)
                        """,
                        (
                            item["item_id"], group_id, occurrence_start, occurrence_end,
                            req.reason_category, reason, current_user.user_id,
                        ),
                    )
                    blackout_id = cursor.lastrowid
                    blackout_ids.append(blackout_id)
                    if created_at is None:
                        cursor.execute(
                            "SELECT created_at FROM equipment_blackout_periods WHERE equipment_blackout_id = %s",
                            (blackout_id,),
                        )
                        created_at = cursor.fetchone()["created_at"]
                    log_system_audit(
                        cursor,
                        entity_type="EquipmentBlackout",
                        entity_id=blackout_id,
                        action="Created",
                        changed_by=current_user.user_id,
                        new_values={
                            "item_id": item["item_id"],
                            "blackout_group_id": group_id,
                            "start_datetime": occurrence_start.isoformat(),
                            "end_datetime": occurrence_end.isoformat(),
                            "repeat_weekdays": req.repeat_weekdays,
                            "reason_category": req.reason_category,
                            "reason_explanation": reason,
                        },
                        remarks=f"Equipment blackout scheduled by {current_user.name}",
                    )

    if conflicts and not req.confirm_booking_conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"{len(conflicts)} pending or approved equipment booking(s) overlap this blackout.",
                "confirmation_required": True,
                "conflicts": conflicts,
            },
        )

    first_start, first_end = occurrences[0]
    return {
        "equipment_blackout_id": blackout_ids[0],
        "blackout_ids": blackout_ids,
        "blackout_group_id": group_ids[0],
        "blackout_group_ids": group_ids,
        "equipment_count": len(items),
        "occurrence_count": len(occurrences),
        "item_names": [item["item_name"] for item in items],
        "start_datetime": first_start,
        "end_datetime": first_end,
        "reason_category": req.reason_category,
        "reason_explanation": reason,
        "created_by": current_user.user_id,
        "creator_name": current_user.name,
        "created_at": created_at,
    }


@router.patch("/{equipment_blackout_id:int}/cancel")
def cancel_equipment_blackout(
    equipment_blackout_id: int,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
):
    with transaction_scope() as (conn, cursor):
        cursor.execute(
            """
            SELECT blackout_group_id FROM equipment_blackout_periods
            WHERE equipment_blackout_id = %s
            """,
            (equipment_blackout_id,),
        )
        blackout = cursor.fetchone()
        if not blackout:
            raise HTTPException(status_code=404, detail="Equipment blackout not found.")
        group_id = blackout["blackout_group_id"]
        cursor.execute(
            """
            SELECT equipment_blackout_id, item_id FROM equipment_blackout_periods
            WHERE blackout_group_id = %s AND status = 'Active'
            FOR UPDATE
            """,
            (group_id,),
        )
        rows = cursor.fetchall()
        if not rows:
            return {"message": "Equipment blackout was already cancelled.", "cancelled_count": 0}
        cursor.execute(
            """
            UPDATE equipment_blackout_periods
            SET status = 'Cancelled', cancelled_by = %s, cancelled_at = NOW()
            WHERE blackout_group_id = %s AND status = 'Active'
            """,
            (current_user.user_id, group_id),
        )
        for row in rows:
            log_system_audit(
                cursor,
                entity_type="EquipmentBlackout",
                entity_id=row["equipment_blackout_id"],
                action="Cancelled",
                changed_by=current_user.user_id,
                old_values={"status": "Active"},
                new_values={"status": "Cancelled", "blackout_group_id": group_id},
                remarks=f"Equipment blackout cancelled by {current_user.name}",
            )
    return {"message": "Equipment blackout cancelled; its history was retained.", "cancelled_count": len(rows)}
