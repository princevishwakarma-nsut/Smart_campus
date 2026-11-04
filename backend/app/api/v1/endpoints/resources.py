from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.core.permissions import get_current_user_optional, require_roles, UserContext, Role
from app.database.dependencies import get_db
from app.database.transaction import transaction_scope
from app.schemas.resource import (
    ResourceCreate, ResourceUpdate, ResourceStatusUpdate,
    ResourceResponse, ResourceFeatureCreate, ResourceFeatureResponse
)
from app.schemas.operating_hours import OperatingHoursBulkUpdate, OperatingHoursExceptionCreate
from app.services.audit_service import log_system_audit
from app.services.operating_hours import (
    WEEKDAY_INDEX,
    resolve_operating_resources,
    save_weekly_hours,
    validate_exception_ranges,
)

router = APIRouter()


@router.get("/operating-hours", summary="List recurring resource schedules (Admin/Staff)")
def list_operating_hours(
    resource_id: Optional[int] = Query(None, ge=1),
    current_user=Depends(require_roles(Role.ADMIN, Role.STAFF)),
    db=Depends(get_db),
):
    query = """
        SELECT h.operating_hours_id, h.resource_id, h.weekday, h.is_closed, h.is_active,
               h.open_time, h.close_time, h.updated_by, h.updated_at,
               r.resource_name, r.category_id, c.category_name
        FROM resource_operating_hours h
        JOIN resources r ON r.resource_id = h.resource_id
        JOIN categories c ON c.category_id = r.category_id
    """
    params = ()
    if resource_id is not None:
        query += " WHERE h.resource_id = %s"
        params = (resource_id,)
    query += " ORDER BY r.resource_name, h.weekday"
    db.execute(query, params)
    schedules = db.fetchall()
    return [
        {
            **row,
            "weekday_name": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[row["weekday"]],
            "open_time": str(row["open_time"]) if row["open_time"] is not None else None,
            "close_time": str(row["close_time"]) if row["close_time"] is not None else None,
        }
        for row in schedules
    ]


@router.put("/operating-hours/bulk", summary="Apply recurring hours to resources, categories, or all resources")
def update_operating_hours(
    req: OperatingHoursBulkUpdate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
):
    with transaction_scope() as (conn, cursor):
        resources = resolve_operating_resources(
            cursor, req.resource_ids, req.category_ids, req.all_resources, lock=True
        )
        save_weekly_hours(cursor, resources, req, current_user.user_id)
        summary = {
            "weekdays": req.weekdays,
            "closed_days": req.closed_days,
            "open_time": req.open_time.isoformat() if req.open_time else None,
            "close_time": req.close_time.isoformat() if req.close_time else None,
            "is_active": req.is_active,
            "is_active": req.is_active,
        }
        for resource in resources:
            log_system_audit(
                cursor,
                entity_type="ResourceOperatingHours",
                entity_id=resource["resource_id"],
                action="Updated",
                changed_by=current_user.user_id,
                new_values=summary,
                remarks=f"Recurring hours updated for {resource['resource_name']}",
            )
    return {
        "resource_count": len(resources),
        "resources": [
            {"resource_id": row["resource_id"], "resource_name": row["resource_name"]}
            for row in resources
        ],
        "weekday_count": len(set(req.weekdays) | set(req.closed_days)),
    }


@router.get("/operating-hours/exceptions", summary="List resource operating-hours exceptions (Admin/Staff)")
def list_operating_hour_exceptions(
    resource_id: Optional[int] = Query(None, ge=1),
    status_filter: str = Query("Active", alias="status", pattern="^(Active|Cancelled|All)$"),
    current_user=Depends(require_roles(Role.ADMIN, Role.STAFF)),
    db=Depends(get_db),
):
    query = """
        SELECT e.exception_id, e.resource_id, e.start_date, e.end_date, e.is_closed,
               e.open_time, e.close_time, e.reason, e.status, e.created_by,
               e.created_at, e.cancelled_by, e.cancelled_at,
               r.resource_name, c.category_name, u.name AS creator_name
        FROM resource_operating_hour_exceptions e
        JOIN resources r ON r.resource_id = e.resource_id
        JOIN categories c ON c.category_id = r.category_id
        LEFT JOIN users u ON u.user_id = e.created_by
        WHERE 1=1
    """
    params = []
    if resource_id is not None:
        query += " AND e.resource_id = %s"
        params.append(resource_id)
    if status_filter != "All":
        query += " AND e.status = %s"
        params.append(status_filter)
    query += " ORDER BY e.start_date DESC, e.exception_id DESC"
    db.execute(query, tuple(params))
    rows = db.fetchall()
    return [
        {
            **row,
            "open_time": str(row["open_time"]) if row["open_time"] is not None else None,
            "close_time": str(row["close_time"]) if row["close_time"] is not None else None,
        }
        for row in rows
    ]


@router.post("/operating-hours/exceptions", status_code=status.HTTP_201_CREATED, summary="Create a date-specific operating-hours exception")
def create_operating_hour_exception(
    req: OperatingHoursExceptionCreate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
):
    with transaction_scope() as (conn, cursor):
        resources = resolve_operating_resources(
            cursor, req.resource_ids, req.category_ids, req.all_resources, lock=True
        )
        validate_exception_ranges(cursor, resources, req.start_date, req.end_date)
        exception_ids = []
        for resource in resources:
            cursor.execute(
                """
                INSERT INTO resource_operating_hour_exceptions
                    (resource_id, start_date, end_date, is_closed, open_time, close_time, reason, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    resource["resource_id"], req.start_date, req.end_date, req.is_closed,
                    req.open_time, req.close_time, req.reason.strip(), current_user.user_id,
                ),
            )
            exception_ids.append(cursor.lastrowid)
            log_system_audit(
                cursor,
                entity_type="ResourceOperatingHoursException",
                entity_id=cursor.lastrowid,
                action="Created",
                changed_by=current_user.user_id,
                new_values={
                    "resource_id": resource["resource_id"],
                    "start_date": req.start_date.isoformat(),
                    "end_date": req.end_date.isoformat(),
                    "is_closed": req.is_closed,
                    "open_time": req.open_time.isoformat() if req.open_time else None,
                    "close_time": req.close_time.isoformat() if req.close_time else None,
                    "reason": req.reason.strip(),
                },
            )
    return {"exception_ids": exception_ids, "resource_count": len(resources)}


@router.patch("/operating-hours/exceptions/{exception_id}/cancel", summary="Cancel a resource operating-hours exception")
def cancel_operating_hour_exception(
    exception_id: int,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
):
    with transaction_scope() as (conn, cursor):
        cursor.execute(
            "SELECT resource_id, status, reason FROM resource_operating_hour_exceptions WHERE exception_id = %s FOR UPDATE",
            (exception_id,),
        )
        exception = cursor.fetchone()
        if not exception:
            raise HTTPException(status_code=404, detail="Operating-hours exception not found.")
        if exception["status"] == "Cancelled":
            raise HTTPException(status_code=409, detail="Operating-hours exception is already cancelled.")
        cursor.execute(
            """
            UPDATE resource_operating_hour_exceptions
            SET status = 'Cancelled', cancelled_by = %s, cancelled_at = NOW()
            WHERE exception_id = %s
            """,
            (current_user.user_id, exception_id),
        )
        log_system_audit(
            cursor,
            entity_type="ResourceOperatingHoursException",
            entity_id=exception_id,
            action="Cancelled",
            changed_by=current_user.user_id,
            old_values={"status": "Active", "reason": exception["reason"]},
            new_values={"status": "Cancelled"},
        )
    return {"exception_id": exception_id, "status": "Cancelled"}


@router.get("", response_model=List[ResourceResponse], summary="List all campus resources")
@router.get("/", response_model=List[ResourceResponse], include_in_schema=False)
def list_resources(
    category_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    db=Depends(get_db)
):
    query = """
        SELECT r.resource_id, r.category_id, r.resource_name, r.resource_code, r.location, r.operating_hours,
               r.capacity, r.status, r.description, r.created_at, r.updated_at,
               c.category_name
        FROM resources r
        JOIN categories c ON r.category_id = c.category_id
        WHERE 1=1
    """
    params = []
    if category_id:
        query += " AND r.category_id = %s"
        params.append(category_id)
    if status and status != "All":
        query += " AND r.status = %s"
        params.append(status)
    if location and location != "All":
        query += " AND r.location LIKE %s"
        params.append(f"%{location}%")
    if q:
        query += " AND (r.resource_name LIKE %s OR r.resource_code LIKE %s OR r.location LIKE %s OR r.description LIKE %s)"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"])

    query += " ORDER BY c.category_id, r.resource_name ASC"
    db.execute(query, tuple(params))
    resources = db.fetchall()

    # Fetch features for each resource
    db.execute("SELECT resource_id, feature_name FROM resource_features")
    all_features = db.fetchall()
    features_map = {}
    for f in all_features:
        rid = f["resource_id"]
        features_map.setdefault(rid, []).append(f["feature_name"])

    result = []
    for r in resources:
        res_id = r["resource_id"]
        result.append(
            ResourceResponse(
                resource_id=res_id,
                category_id=r["category_id"],
                category_name=r["category_name"],
                resource_name=r["resource_name"],
                resource_code=r["resource_code"],
                location=r["location"],
                operating_hours=r["operating_hours"],
                capacity=r["capacity"],
                status=r["status"],
                description=r["description"],
                features=features_map.get(res_id, []),
                created_at=r["created_at"],
                updated_at=r["updated_at"]
            )
        )
    return result


@router.get("/departments", summary="List departments alias")
@router.get("/departments/", summary="List departments alias with slash", include_in_schema=False)
def list_departments_alias(db=Depends(get_db)):
    db.execute("SELECT department_id, department_name, department_name as name, description, office_location, contact_email, contact_phone FROM departments WHERE is_active = 1 ORDER BY department_name")
    return db.fetchall()


@router.get("/{resource_id}", response_model=ResourceResponse, summary="Get single resource details")
def get_resource(resource_id: int, db=Depends(get_db)):
    db.execute(
        """
        SELECT r.resource_id, r.category_id, r.resource_name, r.resource_code, r.location, r.operating_hours,
               r.capacity, r.status, r.description, r.created_at, r.updated_at,
               c.category_name
        FROM resources r
        JOIN categories c ON r.category_id = c.category_id
        WHERE r.resource_id = %s
        """,
        (resource_id,)
    )
    r = db.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Resource not found")

    db.execute("SELECT feature_name FROM resource_features WHERE resource_id = %s", (resource_id,))
    features = [f["feature_name"] for f in db.fetchall()]

    return ResourceResponse(
        resource_id=r["resource_id"],
        category_id=r["category_id"],
        category_name=r["category_name"],
        resource_name=r["resource_name"],
        resource_code=r["resource_code"],
        location=r["location"],
        operating_hours=r["operating_hours"],
        capacity=r["capacity"],
        status=r["status"],
        description=r["description"],
        features=features,
        created_at=r["created_at"],
        updated_at=r["updated_at"]
    )


@router.post("", response_model=ResourceResponse, status_code=status.HTTP_201_CREATED, summary="Add a new resource (Admin)")
def create_resource(
    req: ResourceCreate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    # 1. Validate category existence
    db.execute("SELECT category_id FROM categories WHERE category_id = %s", (req.category_id,))
    if not db.fetchone():
        raise HTTPException(status_code=400, detail=f"Category ID {req.category_id} does not exist.")

    # 2. Check duplicate resource code
    code = req.resource_code.strip()
    db.execute("SELECT resource_id FROM resources WHERE resource_code = %s", (code,))
    if db.fetchone():
        raise HTTPException(status_code=400, detail=f"Resource with code '{code}' already exists.")

    with transaction_scope() as (conn, cursor):
        cursor.execute(
            """
            INSERT INTO resources (category_id, resource_name, resource_code, location, operating_hours, capacity, status, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                req.category_id,
                req.resource_name.strip(),
                code,
                req.location.strip(),
                req.operating_hours.strip() if req.operating_hours else None,
                req.capacity,
                req.status or "Available",
                req.description
            )
        )
        res_id = cursor.lastrowid

        if req.features:
            for feat in req.features:
                if feat.strip():
                    cursor.execute(
                        "INSERT INTO resource_features (resource_id, feature_name) VALUES (%s, %s)",
                        (res_id, feat.strip())
                    )

    return get_resource(res_id, db)


@router.put("/{resource_id}", response_model=ResourceResponse, summary="Edit a resource (Admin)")
def update_resource(
    resource_id: int,
    req: ResourceUpdate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    if req.category_id is not None:
        db.execute("SELECT category_id FROM categories WHERE category_id = %s", (req.category_id,))
        if not db.fetchone():
            raise HTTPException(status_code=400, detail=f"Category ID {req.category_id} does not exist.")

    if req.resource_code is not None:
        db.execute("SELECT resource_id FROM resources WHERE resource_code = %s AND resource_id != %s", (req.resource_code.strip(), resource_id))
        if db.fetchone():
            raise HTTPException(status_code=400, detail=f"Resource with code '{req.resource_code}' already exists.")

    with transaction_scope() as (conn, cursor):
        updates = []
        params = []
        if req.category_id is not None:
            updates.append("category_id = %s")
            params.append(req.category_id)
        if req.resource_name is not None:
            updates.append("resource_name = %s")
            params.append(req.resource_name.strip())
        if req.resource_code is not None:
            updates.append("resource_code = %s")
            params.append(req.resource_code.strip())
        if req.location is not None:
            updates.append("location = %s")
            params.append(req.location.strip())
        if "operating_hours" in req.model_fields_set:
            updates.append("operating_hours = %s")
            params.append(req.operating_hours.strip() if req.operating_hours else None)
        if req.capacity is not None:
            updates.append("capacity = %s")
            params.append(req.capacity)
        if req.status is not None:
            updates.append("status = %s")
            params.append(req.status)
        if req.description is not None:
            updates.append("description = %s")
            params.append(req.description)

        if updates:
            params.append(resource_id)
            cursor.execute(f"UPDATE resources SET {', '.join(updates)} WHERE resource_id = %s", tuple(params))

        if req.features is not None:
            cursor.execute("DELETE FROM resource_features WHERE resource_id = %s", (resource_id,))
            for feat in req.features:
                if feat.strip():
                    cursor.execute(
                        "INSERT INTO resource_features (resource_id, feature_name) VALUES (%s, %s)",
                        (resource_id, feat.strip())
                    )

    return get_resource(resource_id, db)


@router.patch("/{resource_id}/status", summary="Change resource status (Admin)")
def update_resource_status(
    resource_id: int,
    req: ResourceStatusUpdate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    if req.status not in ("Available", "Maintenance", "Inactive"):
        raise HTTPException(status_code=400, detail="Invalid status value.")

    db.execute("UPDATE resources SET status = %s WHERE resource_id = %s", (req.status, resource_id))
    return {"message": f"Resource status updated to {req.status} successfully.", "status": req.status, "resource_id": resource_id}


@router.get("/{resource_id}/features", response_model=List[ResourceFeatureResponse], summary="Get resource features")
def get_resource_features(resource_id: int, db=Depends(get_db)):
    db.execute(
        "SELECT feature_id, resource_id, feature_name, description FROM resource_features WHERE resource_id = %s",
        (resource_id,)
    )
    rows = db.fetchall()
    return [
        ResourceFeatureResponse(
            feature_id=r["feature_id"],
            resource_id=r["resource_id"],
            feature_name=r["feature_name"],
            description=r["description"]
        )
        for r in rows
    ]


@router.post("/{resource_id}/features", response_model=ResourceFeatureResponse, status_code=status.HTTP_201_CREATED, summary="Add feature to resource (Admin)")
def add_resource_feature(
    resource_id: int,
    req: ResourceFeatureCreate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    db.execute(
        "INSERT INTO resource_features (resource_id, feature_name, description) VALUES (%s, %s, %s)",
        (resource_id, req.feature_name.strip(), req.description)
    )
    feat_id = db.lastrowid
    return ResourceFeatureResponse(
        feature_id=feat_id,
        resource_id=resource_id,
        feature_name=req.feature_name.strip(),
        description=req.description
    )
