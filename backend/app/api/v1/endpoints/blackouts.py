from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.core.permissions import require_roles, UserContext, Role
from app.database.dependencies import get_db
from app.database.transaction import transaction_scope
from app.schemas.blackout import BlackoutCreate, BlackoutResponse
from app.services.audit_service import log_system_audit

router = APIRouter()


@router.get("", response_model=List[BlackoutResponse], summary="List resource blackout periods (Admin/Staff)")
@router.get("/", response_model=List[BlackoutResponse], include_in_schema=False)
def list_blackouts(
    resource_id: Optional[int] = Query(None),
    current_user: UserContext = Depends(require_roles(Role.ADMIN, Role.STAFF)),
    db=Depends(get_db)
):
    query = """
        SELECT bo.blackout_id, bo.resource_id, bo.maintenance_id, bo.start_datetime, bo.end_datetime,
               bo.reason, bo.created_by, bo.created_at,
               r.resource_name, u.name as creator_name
        FROM resource_blackout_periods bo
        JOIN resources r ON bo.resource_id = r.resource_id
        JOIN users u ON bo.created_by = u.user_id
        WHERE 1=1
    """
    params = []
    if resource_id:
        query += " AND bo.resource_id = %s"
        params.append(resource_id)

    query += " ORDER BY bo.start_datetime DESC"
    db.execute(query, tuple(params))
    rows = db.fetchall()

    return [
        BlackoutResponse(
            blackout_id=r["blackout_id"],
            resource_id=r["resource_id"],
            resource_name=r["resource_name"],
            maintenance_id=r["maintenance_id"],
            start_datetime=r["start_datetime"],
            end_datetime=r["end_datetime"],
            reason=r["reason"],
            created_by=r["created_by"],
            creator_name=r["creator_name"],
            created_at=r["created_at"]
        )
        for r in rows
    ]


@router.post("", response_model=BlackoutResponse, status_code=status.HTTP_201_CREATED, summary="Create manual event/holiday blackout (Admin)")
def create_blackout(
    req: BlackoutCreate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    s_dt = datetime.fromisoformat(req.start_datetime.replace("Z", "+00:00")).replace(tzinfo=None)
    e_dt = datetime.fromisoformat(req.end_datetime.replace("Z", "+00:00")).replace(tzinfo=None)

    if e_dt <= s_dt:
        raise HTTPException(status_code=400, detail="End datetime must be after start datetime.")

    with transaction_scope() as (conn, cursor):
        cursor.execute(
            """
            INSERT INTO resource_blackout_periods (resource_id, maintenance_id, start_datetime, end_datetime, reason, created_by)
            VALUES (%s, NULL, %s, %s, %s, %s)
            """,
            (req.resource_id, s_dt, e_dt, req.reason.strip(), current_user.user_id)
        )
        b_id = cursor.lastrowid

        log_system_audit(
            cursor,
            entity_type="Blackout",
            entity_id=b_id,
            action="Created",
            changed_by=current_user.user_id,
            old_values=None,
            new_values={"resource_id": req.resource_id, "reason": req.reason.strip()},
            remarks=f"Manual blackout scheduled by {current_user.name}"
        )

    db.execute(
        """
        SELECT bo.blackout_id, bo.resource_id, bo.maintenance_id, bo.start_datetime, bo.end_datetime,
               bo.reason, bo.created_by, bo.created_at,
               r.resource_name, u.name as creator_name
        FROM resource_blackout_periods bo
        JOIN resources r ON bo.resource_id = r.resource_id
        JOIN users u ON bo.created_by = u.user_id
        WHERE bo.blackout_id = %s
        """,
        (b_id,)
    )
    row = db.fetchone()

    return BlackoutResponse(
        blackout_id=row["blackout_id"],
        resource_id=row["resource_id"],
        resource_name=row["resource_name"],
        maintenance_id=row["maintenance_id"],
        start_datetime=row["start_datetime"],
        end_datetime=row["end_datetime"],
        reason=row["reason"],
        created_by=row["created_by"],
        creator_name=row["creator_name"],
        created_at=row["created_at"]
    )


@router.delete("/{blackout_id}", summary="Delete blackout period (Admin)")
def delete_blackout(
    blackout_id: int,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    db.execute("SELECT blackout_id, resource_id, reason, maintenance_id FROM resource_blackout_periods WHERE blackout_id = %s", (blackout_id,))
    bo = db.fetchone()
    if not bo:
        raise HTTPException(status_code=404, detail="Blackout record not found.")

    with transaction_scope() as (conn, cursor):
        cursor.execute("DELETE FROM resource_blackout_periods WHERE blackout_id = %s", (blackout_id,))

        log_system_audit(
            cursor,
            entity_type="Blackout",
            entity_id=blackout_id,
            action="Deleted",
            changed_by=current_user.user_id,
            old_values={"resource_id": bo["resource_id"], "reason": bo["reason"]},
            new_values=None,
            remarks=f"Blackout period removed by {current_user.name}"
        )

    return {"message": "Blackout period deleted successfully."}
