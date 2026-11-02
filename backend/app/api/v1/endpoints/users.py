from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.core.permissions import get_current_user, require_roles, UserContext, Role
from app.core.security import get_password_hash
from app.database.dependencies import get_db
from app.database.transaction import transaction_scope
from app.schemas.auth import UserResponse, FacultyRequestResponse, ReviewActionRequest
from app.schemas.user import UserCreateAdmin, UserUpdate, UserStatusUpdate, AdminResetPasswordRequest
from app.services.audit_service import log_system_audit

router = APIRouter()


@router.get("", response_model=List[UserResponse], summary="List users (Admin/Staff/Faculty)")
def list_users(
    role: Optional[str] = Query(None),
    department_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None),
    current_user: UserContext = Depends(require_roles(Role.ADMIN, Role.STAFF, Role.FACULTY)),
    db=Depends(get_db)
):
    query = """
        SELECT u.user_id, u.department_id, u.name, u.email, u.role, u.phone_no, u.is_active,
               d.department_name
        FROM users u
        LEFT JOIN departments d ON u.department_id = d.department_id
        WHERE 1=1
    """
    params = []
    if role and role != "All":
        query += " AND u.role = %s"
        params.append(role)
    if department_id:
        query += " AND u.department_id = %s"
        params.append(department_id)
    if q:
        query += " AND (u.name LIKE %s OR u.email LIKE %s OR u.phone_no LIKE %s)"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    query += " ORDER BY u.role ASC, u.name ASC"
    db.execute(query, tuple(params))
    rows = db.fetchall()

    return [
        UserResponse(
            user_id=r["user_id"],
            name=r["name"],
            email=r["email"],
            role=r["role"],
            department_id=r["department_id"],
            department_name=r["department_name"],
            phone_no=r["phone_no"],
            is_active=bool(r["is_active"])
        )
        for r in rows
    ]



@router.get("/faculty-requests", response_model=List[FacultyRequestResponse], summary="List faculty registration requests (Admin only)")
def list_faculty_requests(
    status: Optional[str] = Query(None),
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    query = """
        SELECT fr.request_id, fr.name, fr.email, fr.department_id, fr.phone_no,
               fr.employee_id, fr.designation, fr.status, fr.reviewed_by, fr.reviewed_at,
               fr.rejection_reason, fr.created_at, d.department_name
        FROM faculty_requests fr
        LEFT JOIN departments d ON fr.department_id = d.department_id
        WHERE 1=1
    """
    params = []
    if status and status != "All":
        query += " AND fr.status = %s"
        params.append(status)

    query += " ORDER BY fr.request_id DESC"
    db.execute(query, tuple(params))
    rows = db.fetchall()

    return [
        FacultyRequestResponse(
            request_id=r["request_id"],
            name=r["name"],
            email=r["email"],
            department_id=r["department_id"],
            department_name=r["department_name"],
            phone_no=r["phone_no"],
            employee_id=r["employee_id"],
            designation=r["designation"],
            status=r["status"],
            reviewed_by=r["reviewed_by"],
            reviewed_at=str(r["reviewed_at"]) if r["reviewed_at"] else None,
            rejection_reason=r["rejection_reason"],
            created_at=str(r["created_at"]) if r["created_at"] else None
        )
        for r in rows
    ]


@router.post("/faculty-requests/{request_id}/approve", summary="Approve faculty registration request (Admin only)")
def approve_faculty_request(
    request_id: int,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    db.execute("SELECT * FROM faculty_requests WHERE request_id = %s", (request_id,))
    freq = db.fetchone()
    if not freq:
        raise HTTPException(status_code=404, detail="Faculty request not found.")

    if freq["status"] != "Pending":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve faculty request that is already {freq['status']}."
        )

    with transaction_scope() as (conn, cursor):
        # 1. Locate existing user record to preserve original user_id and email
        user_id = freq.get("user_id")
        existing_user = None
        if user_id:
            cursor.execute("SELECT user_id, email, password_hash FROM users WHERE user_id = %s", (user_id,))
            existing_user = cursor.fetchone()
        if not existing_user:
            cursor.execute("SELECT user_id, email, password_hash FROM users WHERE email = %s", (freq["email"],))
            existing_user = cursor.fetchone()

        if existing_user:
            # Preserve original user_id and update account to active Faculty
            target_user_id = existing_user["user_id"]
            cursor.execute(
                """
                UPDATE users
                SET role = 'Faculty',
                    is_active = 1,
                    name = %s,
                    department_id = COALESCE(%s, department_id),
                    phone_no = COALESCE(%s, phone_no),
                    password_hash = COALESCE(%s, password_hash)
                WHERE user_id = %s
                """,
                (
                    freq["name"],
                    freq["department_id"],
                    freq["phone_no"],
                    freq["password_hash"],
                    target_user_id
                )
            )
        else:
            # If not pre-created, insert user record with role 'Faculty' and is_active=1
            cursor.execute(
                """
                INSERT INTO users (department_id, name, email, password_hash, role, phone_no, is_active)
                VALUES (%s, %s, %s, %s, 'Faculty', %s, 1)
                """,
                (
                    freq["department_id"],
                    freq["name"],
                    freq["email"],
                    freq["password_hash"],
                    freq["phone_no"]
                )
            )
            target_user_id = cursor.lastrowid

        # 2. Update faculty_requests record
        cursor.execute(
            """
            UPDATE faculty_requests
            SET status = 'Approved', user_id = %s, reviewed_by = %s, reviewed_at = CURRENT_TIMESTAMP
            WHERE request_id = %s
            """,
            (target_user_id, current_user.user_id, request_id)
        )

        # 3. Log System Audit
        log_system_audit(
            cursor,
            entity_type="FacultyRequest",
            entity_id=request_id,
            action="Approved",
            changed_by=current_user.user_id,
            old_values={"status": "Pending"},
            new_values={"status": "Approved", "user_id": target_user_id},
            remarks=f"Faculty registration for {freq['name']} approved by Admin {current_user.name}"
        )

        # 4. Insert notification for the approved faculty member
        cursor.execute(
            """
            INSERT INTO notifications (user_id, message, type, is_read)
            VALUES (%s, 'Your faculty account has been approved and activated. You can now access your teaching dashboard and book campus spaces.', 'Approval', 0)
            """,
            (target_user_id,)
        )

    return {
        "message": f"Faculty account for '{freq['name']}' has been approved and activated.",
        "user_id": target_user_id,
        "request_id": request_id,
        "status": "Approved"
    }


@router.post("/faculty-requests/{request_id}/reject", summary="Reject faculty registration request (Admin only)")
def reject_faculty_request(
    request_id: int,
    req: ReviewActionRequest,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    db.execute("SELECT * FROM faculty_requests WHERE request_id = %s", (request_id,))
    freq = db.fetchone()
    if not freq:
        raise HTTPException(status_code=404, detail="Faculty request not found.")

    if freq["status"] != "Pending":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reject faculty request that is already {freq['status']}."
        )

    reason = req.reason.strip() if req.reason else "Request details could not be verified."

    with transaction_scope() as (conn, cursor):
        user_id = freq.get("user_id")
        if user_id:
            cursor.execute("UPDATE users SET is_active = 0 WHERE user_id = %s", (user_id,))
        else:
            cursor.execute("UPDATE users SET is_active = 0 WHERE email = %s", (freq["email"],))

        cursor.execute(
            """
            UPDATE faculty_requests
            SET status = 'Rejected', rejection_reason = %s, reviewed_by = %s, reviewed_at = CURRENT_TIMESTAMP
            WHERE request_id = %s
            """,
            (reason, current_user.user_id, request_id)
        )

        log_system_audit(
            cursor,
            entity_type="FacultyRequest",
            entity_id=request_id,
            action="Rejected",
            changed_by=current_user.user_id,
            old_values={"status": "Pending"},
            new_values={"status": "Rejected", "reason": reason},
            remarks=f"Faculty registration for {freq['name']} rejected by Admin {current_user.name}: {reason}"
        )

    return {
        "message": f"Faculty registration request for '{freq['name']}' has been rejected.",
        "request_id": request_id,
        "status": "Rejected"
    }


@router.get("/{user_id}", response_model=UserResponse, summary="Get user by ID")
def get_user_by_id(user_id: int, current_user: UserContext = Depends(get_current_user), db=Depends(get_db)):
    if not (current_user.is_admin() or current_user.is_staff()) and current_user.user_id != user_id:
        raise HTTPException(status_code=403, detail="Cannot access profile of another user.")

    db.execute(
        """
        SELECT u.user_id, u.department_id, u.name, u.email, u.role, u.phone_no, u.is_active,
               d.department_name
        FROM users u
        LEFT JOIN departments d ON u.department_id = d.department_id
        WHERE u.user_id = %s
        """,
        (user_id,)
    )
    user = db.fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return UserResponse(
        user_id=user["user_id"],
        name=user["name"],
        email=user["email"],
        role=user["role"],
        department_id=user["department_id"],
        department_name=user["department_name"],
        phone_no=user["phone_no"],
        is_active=bool(user["is_active"])
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED, summary="Create user account (Admin only)")
def create_user_admin(
    req: UserCreateAdmin,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    email = req.email.strip().lower()

    if req.role not in (Role.STUDENT.value, Role.FACULTY.value, Role.STAFF.value, Role.ADMIN.value):
        raise HTTPException(status_code=400, detail="Invalid role specified. Supported: Student, Faculty, Staff, Admin")

    db.execute("SELECT user_id FROM users WHERE email = %s", (email,))
    if db.fetchone():
        raise HTTPException(status_code=400, detail="A user with this email already exists.")

    password_hash = get_password_hash(req.password)

    with transaction_scope() as (conn, cursor):
        cursor.execute(
            """
            INSERT INTO users (department_id, name, email, password_hash, role, phone_no, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, 1)
            """,
            (req.department_id, req.name.strip(), email, password_hash, req.role, req.phone_no)
        )
        new_id = cursor.lastrowid

        log_system_audit(
            cursor,
            entity_type="User",
            entity_id=new_id,
            action="Created",
            changed_by=current_user.user_id,
            old_values=None,
            new_values={"name": req.name.strip(), "email": email, "role": req.role},
            remarks=f"User account created by Admin {current_user.name}"
        )

    return get_user_by_id(new_id, current_user, db)


@router.put("/{user_id}", response_model=UserResponse, summary="Update user profile")
def update_user(user_id: int, req: UserUpdate, current_user: UserContext = Depends(get_current_user), db=Depends(get_db)):
    if not current_user.is_admin() and current_user.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this user.")

    # Only Admin can change role
    if req.role and not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Only administrators can modify user roles.")

    # Fetch old values for audit
    db.execute("SELECT name, department_id, phone_no, role FROM users WHERE user_id = %s", (user_id,))
    old_row = db.fetchone()
    if not old_row:
        raise HTTPException(status_code=404, detail="User not found")

    updates = []
    params = []
    if req.name is not None:
        updates.append("name = %s")
        params.append(req.name.strip())
    if req.department_id is not None:
        updates.append("department_id = %s")
        params.append(req.department_id)
    if req.phone_no is not None:
        updates.append("phone_no = %s")
        params.append(req.phone_no.strip())
    if req.role is not None and current_user.is_admin():
        if req.role not in (Role.STUDENT.value, Role.FACULTY.value, Role.STAFF.value, Role.ADMIN.value):
            raise HTTPException(status_code=400, detail="Invalid role.")
        updates.append("role = %s")
        params.append(req.role)

    if updates:
        with transaction_scope() as (conn, cursor):
            params.append(user_id)
            cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE user_id = %s", tuple(params))

            log_system_audit(
                cursor,
                entity_type="User",
                entity_id=user_id,
                action="Updated",
                changed_by=current_user.user_id,
                old_values=dict(old_row),
                new_values=req.model_dump(exclude_unset=True),
                remarks=f"User updated by {current_user.name}"
            )

    return get_user_by_id(user_id, current_user, db)


@router.post("/{user_id}/reset-password", summary="Admin reset another user's password (Admin only)")
def admin_reset_password(
    user_id: int,
    req: AdminResetPasswordRequest,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    """Admin resets another user's password, invalidating that user's existing sessions."""
    db.execute("SELECT user_id, name, email, role FROM users WHERE user_id = %s", (user_id,))
    target_user = db.fetchone()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if len(req.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters long."
        )

    new_hash = get_password_hash(req.new_password)
    with transaction_scope() as (conn, cursor):
        cursor.execute(
            """
            UPDATE users
            SET password_hash = %s, token_version = token_version + 1, updated_at = NOW()
            WHERE user_id = %s
            """,
            (new_hash, user_id)
        )
        log_system_audit(
            cursor,
            entity_type="User",
            entity_id=user_id,
            action="PasswordReset",
            changed_by=current_user.user_id,
            old_values=None,
            new_values=None,
            remarks=f"Admin {current_user.name} reset password for {target_user['name']} ({target_user['email']})"
        )

    return {
        "success": True,
        "message": f"Password reset successfully for {target_user['name']}. Existing sessions for this user have been invalidated."
    }


@router.patch("/{user_id}/status", summary="Activate or deactivate user (Admin only)")
def update_user_status(user_id: int, req: UserStatusUpdate, current_user: UserContext = Depends(require_roles(Role.ADMIN)), db=Depends(get_db)):
    if user_id == current_user.user_id and not req.is_active:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own Admin account.")

    with transaction_scope() as (conn, cursor):
        cursor.execute(
            """
            UPDATE users
            SET is_active = %s,
                token_version = CASE WHEN %s = 0 THEN token_version + 1 ELSE token_version END
            WHERE user_id = %s
            """,
            (1 if req.is_active else 0, 1 if req.is_active else 0, user_id)
        )

        log_system_audit(
            cursor,
            entity_type="User",
            entity_id=user_id,
            action="StatusChanged",
            changed_by=current_user.user_id,
            old_values={"is_active": not req.is_active},
            new_values={"is_active": req.is_active},
            remarks=f"Account {'activated' if req.is_active else 'deactivated'} by Admin {current_user.name}"
        )

    return {"message": f"User {'activated' if req.is_active else 'deactivated'} successfully."}
