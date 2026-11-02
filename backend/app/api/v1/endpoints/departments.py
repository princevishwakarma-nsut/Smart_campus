from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.permissions import require_roles, UserContext, Role
from app.database.dependencies import get_db
from app.schemas.department import DepartmentCreate, DepartmentUpdate, DepartmentResponse

router = APIRouter()


@router.get("", response_model=List[DepartmentResponse], summary="List all departments")
@router.get("/", response_model=List[DepartmentResponse], include_in_schema=False)
def list_departments(db=Depends(get_db)):
    db.execute(
        """
        SELECT department_id, department_name, description, hod_user_id, office_location,
               contact_email, contact_phone, created_at, is_active
        FROM departments
        ORDER BY department_name ASC
        """
    )
    rows = db.fetchall()
    return [
        DepartmentResponse(
            department_id=r["department_id"],
            department_name=r["department_name"],
            description=r["description"],
            hod_user_id=r["hod_user_id"],
            office_location=r["office_location"],
            contact_email=r["contact_email"],
            contact_phone=r["contact_phone"],
            created_at=r["created_at"],
            is_active=bool(r["is_active"])
        )
        for r in rows
    ]


@router.post("", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED, summary="Create department (Admin)")
def create_department(req: DepartmentCreate, current_user: UserContext = Depends(require_roles(Role.ADMIN)), db=Depends(get_db)):
    db.execute("SELECT department_id FROM departments WHERE department_name = %s", (req.department_name.strip(),))
    if db.fetchone():
        raise HTTPException(status_code=400, detail="Department with this name already exists.")

    db.execute(
        """
        INSERT INTO departments (department_name, description, hod_user_id, office_location, contact_email, contact_phone, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            req.department_name.strip(),
            req.description,
            req.hod_user_id,
            req.office_location,
            req.contact_email,
            req.contact_phone,
            1 if req.is_active else 0
        )
    )
    dept_id = db.lastrowid
    db.execute("SELECT * FROM departments WHERE department_id = %s", (dept_id,))
    row = db.fetchone()

    return DepartmentResponse(
        department_id=row["department_id"],
        department_name=row["department_name"],
        description=row["description"],
        hod_user_id=row["hod_user_id"],
        office_location=row["office_location"],
        contact_email=row["contact_email"],
        contact_phone=row["contact_phone"],
        created_at=row["created_at"],
        is_active=bool(row["is_active"])
    )


@router.put("/{department_id}", response_model=DepartmentResponse, summary="Update department (Admin)")
def update_department(department_id: int, req: DepartmentUpdate, current_user: UserContext = Depends(require_roles(Role.ADMIN)), db=Depends(get_db)):
    updates = []
    params = []
    if req.department_name is not None:
        updates.append("department_name = %s")
        params.append(req.department_name.strip())
    if req.description is not None:
        updates.append("description = %s")
        params.append(req.description)
    if req.hod_user_id is not None:
        updates.append("hod_user_id = %s")
        params.append(req.hod_user_id)
    if req.office_location is not None:
        updates.append("office_location = %s")
        params.append(req.office_location)
    if req.contact_email is not None:
        updates.append("contact_email = %s")
        params.append(req.contact_email)
    if req.contact_phone is not None:
        updates.append("contact_phone = %s")
        params.append(req.contact_phone)
    if req.is_active is not None:
        updates.append("is_active = %s")
        params.append(1 if req.is_active else 0)

    if updates:
        params.append(department_id)
        db.execute(f"UPDATE departments SET {', '.join(updates)} WHERE department_id = %s", tuple(params))

    db.execute("SELECT * FROM departments WHERE department_id = %s", (department_id,))
    row = db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Department not found")

    return DepartmentResponse(
        department_id=row["department_id"],
        department_name=row["department_name"],
        description=row["description"],
        hod_user_id=row["hod_user_id"],
        office_location=row["office_location"],
        contact_email=row["contact_email"],
        contact_phone=row["contact_phone"],
        created_at=row["created_at"],
        is_active=bool(row["is_active"])
    )
