from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.core.permissions import get_current_user_optional, require_roles, UserContext, Role
from app.database.dependencies import get_db
from app.database.transaction import transaction_scope
from app.schemas.resource import (
    ResourceCreate, ResourceUpdate, ResourceStatusUpdate,
    ResourceResponse, ResourceFeatureCreate, ResourceFeatureResponse
)

router = APIRouter()


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
        SELECT r.resource_id, r.category_id, r.resource_name, r.resource_code, r.location,
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
        SELECT r.resource_id, r.category_id, r.resource_name, r.resource_code, r.location,
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
            INSERT INTO resources (category_id, resource_name, resource_code, location, capacity, status, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                req.category_id,
                req.resource_name.strip(),
                code,
                req.location.strip(),
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
