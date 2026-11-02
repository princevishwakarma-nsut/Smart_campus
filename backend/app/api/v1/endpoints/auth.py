from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import verify_password, get_password_hash, create_access_token, revoke_token
from app.core.permissions import get_current_user, UserContext, Role
from app.database.dependencies import get_db
from app.database.transaction import transaction_scope
from app.schemas.auth import (
    LoginRequest, RegisterRequest, RegisterFacultyRequest,
    RegisterSocietyRequest, TokenResponse, UserResponse, ChangePasswordRequest
)
from app.services.audit_service import log_system_audit

router = APIRouter()


@router.post("/login", response_model=TokenResponse, summary="Log in with email and password")
def login(creds: LoginRequest, db=Depends(get_db)):
    email = creds.email.strip().lower()
    db.execute(
        """
        SELECT u.user_id, u.department_id, u.name, u.email, u.password_hash, u.role, u.phone_no, u.is_active,
               u.token_version, d.department_name
        FROM users u
        LEFT JOIN departments d ON u.department_id = d.department_id
        WHERE u.email = %s
        """,
        (email,)
    )
    user = db.fetchone()

    # Check if user has a pending or rejected faculty registration request
    db.execute(
        """
        SELECT request_id, status, rejection_reason
        FROM faculty_requests
        WHERE email = %s
        ORDER BY request_id DESC LIMIT 1
        """,
        (email,)
    )
    freq = db.fetchone()

    if not user:
        if freq:
            if freq["status"] == "Pending":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Your faculty registration request is currently pending administrator approval. Please wait for an administrator to review and activate your account."
                )
            elif freq["status"] == "Rejected":
                reason_str = f" Reason: {freq['rejection_reason']}" if freq["rejection_reason"] else ""
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Your faculty registration request was rejected by an administrator.{reason_str}"
                )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify password against Argon2id hash
    if not verify_password(creds.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check account activation status
    if not user["is_active"]:
        if freq and freq["status"] == "Pending":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your faculty registration request is currently pending administrator approval. Please wait for an administrator to review and activate your account."
            )
        elif freq and freq["status"] == "Rejected":
            reason_str = f" Reason: {freq['rejection_reason']}" if freq["rejection_reason"] else ""
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your faculty registration request was rejected by an administrator.{reason_str}"
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated. Please contact an administrator."
        )

    access_token = create_access_token(
        subject=user["user_id"],
        extra_claims={
            "email": user["email"],
            "role": user["role"],
            "name": user["name"],
            "department_id": user["department_id"],
            "token_version": user.get("token_version", 1)
        }
    )

    user_obj = UserResponse(
        user_id=user["user_id"],
        name=user["name"],
        email=user["email"],
        role=user["role"],
        department_id=user["department_id"],
        department_name=user["department_name"],
        phone_no=user["phone_no"],
        is_active=bool(user["is_active"])
    )

    return TokenResponse(access_token=access_token, token_type="bearer", user=user_obj)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED, summary="Public student registration")
@router.post("/register/student", response_model=UserResponse, status_code=status.HTTP_201_CREATED, summary="Public student registration alias")
def register(req: RegisterRequest, db=Depends(get_db)):
    email = req.email.strip().lower()

    # Public registration strictly restricted to Student role only
    if req.role and req.role != Role.STUDENT.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registration is only available for Students. Faculty, Staff, and Admin accounts must be created by an Administrator."
        )

    role = Role.STUDENT.value

    # Validate department if provided
    if req.department_id:
        db.execute("SELECT department_id FROM departments WHERE department_id = %s", (req.department_id,))
        if not db.fetchone():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid department specified."
            )

    db.execute("SELECT user_id FROM users WHERE email = %s", (email,))
    if db.fetchone():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists."
        )

    password_hash = get_password_hash(req.password)

    with transaction_scope() as (conn, cursor):
        cursor.execute(
            """
            INSERT INTO users (department_id, name, email, password_hash, role, phone_no, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, 1)
            """,
            (req.department_id, req.name.strip(), email, password_hash, role, req.phone_no)
        )
        user_id = cursor.lastrowid

        log_system_audit(
            cursor,
            entity_type="User",
            entity_id=user_id,
            action="StudentRegistered",
            changed_by=user_id,
            old_values=None,
            new_values={"name": req.name.strip(), "email": email, "role": role},
            remarks=f"Public student account self-registered by {req.name.strip()}"
        )

    # Fetch created user with department
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


@router.post("/register/faculty", status_code=status.HTTP_201_CREATED, summary="Public faculty registration request")
def register_faculty(req: RegisterFacultyRequest, db=Depends(get_db)):
    email = req.email.strip().lower()

    # 1. Check if an active account with this email already exists in users
    db.execute("SELECT user_id, is_active FROM users WHERE email = %s", (email,))
    existing_user = db.fetchone()
    if existing_user and existing_user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists."
        )

    # 2. Check if a pending request with this email already exists in faculty_requests
    db.execute("SELECT request_id FROM faculty_requests WHERE email = %s AND status = 'Pending'", (email,))
    if db.fetchone():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A faculty registration request with this email is already pending administrator approval."
        )

    # 3. Validate department if provided
    if req.department_id:
        db.execute("SELECT department_id FROM departments WHERE department_id = %s", (req.department_id,))
        if not db.fetchone():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid department specified."
            )

    password_hash = get_password_hash(req.password)

    with transaction_scope() as (conn, cursor):
        # Create or update user record in inactive/pending state (is_active=0)
        if existing_user:
            user_id = existing_user["user_id"]
            cursor.execute(
                """
                UPDATE users
                SET name = %s, password_hash = %s, department_id = %s, phone_no = %s, role = 'Faculty', is_active = 0
                WHERE user_id = %s
                """,
                (req.name.strip(), password_hash, req.department_id, req.phone_no, user_id)
            )
        else:
            cursor.execute(
                """
                INSERT INTO users (department_id, name, email, password_hash, role, phone_no, is_active)
                VALUES (%s, %s, %s, %s, 'Faculty', %s, 0)
                """,
                (req.department_id, req.name.strip(), email, password_hash, req.phone_no)
            )
            user_id = cursor.lastrowid

        cursor.execute(
            """
            INSERT INTO faculty_requests (user_id, name, email, password_hash, department_id, phone_no, employee_id, designation, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Pending')
            """,
            (
                user_id,
                req.name.strip(),
                email,
                password_hash,
                req.department_id,
                req.phone_no,
                req.employee_id.strip(),
                req.designation.strip() if req.designation else None
            )
        )
        request_id = cursor.lastrowid

        log_system_audit(
            cursor,
            entity_type="FacultyRequest",
            entity_id=request_id,
            action="Submitted",
            changed_by=None,
            old_values=None,
            new_values={
                "user_id": user_id,
                "name": req.name.strip(),
                "email": email,
                "employee_id": req.employee_id.strip(),
                "department_id": req.department_id
            },
            remarks=f"Faculty registration request submitted by {req.name.strip()} ({req.employee_id.strip()})"
        )

    return {
        "message": "Faculty registration request submitted successfully. It is pending administrator review and approval.",
        "request_id": request_id,
        "user_id": user_id,
        "status": "Pending"
    }


@router.post("/register/society", status_code=status.HTTP_201_CREATED, summary="Public society registration request")
def register_society(req: RegisterSocietyRequest, db=Depends(get_db)):
    club_name = req.club_name.strip()
    coord_email = req.coordinator_email.strip().lower()

    # 1. Unique club name check
    db.execute("SELECT club_id FROM societies WHERE club_name = %s", (club_name,))
    if db.fetchone():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A society with the name '{club_name}' already exists."
        )

    # 2. Coordinator user validation
    db.execute(
        "SELECT user_id, name, email, role, is_active FROM users WHERE email = %s",
        (coord_email,)
    )
    coord_user = db.fetchone()
    if not coord_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Coordinator account with email '{coord_email}' was not found. The coordinator must be an existing registered Student or Faculty member."
        )

    if not coord_user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Coordinator account with email '{coord_email}' is inactive or disabled."
        )

    if coord_user["role"] not in (Role.STUDENT.value, Role.FACULTY.value, Role.ADMIN.value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Coordinator must be a registered Student or Faculty member."
        )

    # 3. Validate department if provided
    if req.department_id:
        db.execute("SELECT department_id FROM departments WHERE department_id = %s", (req.department_id,))
        if not db.fetchone():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid department specified."
            )

    with transaction_scope() as (conn, cursor):
        # Create society in Pending state (is_active = 0)
        cursor.execute(
            """
            INSERT INTO societies (department_id, club_name, description, faculty_coordinator_id, created_by, established_year, is_active, status)
            VALUES (%s, %s, %s, %s, %s, %s, 0, 'Pending')
            """,
            (
                req.department_id,
                club_name,
                req.description.strip() if req.description else None,
                coord_user["user_id"] if coord_user["role"] == Role.FACULTY.value else None,
                coord_user["user_id"],
                req.established_year
            )
        )
        club_id = cursor.lastrowid

        # Add coordinator to society_members
        cursor.execute(
            """
            INSERT INTO society_members (club_id, user_id, member_role, can_manage, can_book, is_active)
            VALUES (%s, %s, 'Coordinator', 1, 1, 1)
            """,
            (club_id, coord_user["user_id"])
        )

        log_system_audit(
            cursor,
            entity_type="Society",
            entity_id=club_id,
            action="RegistrationSubmitted",
            changed_by=coord_user["user_id"],
            old_values=None,
            new_values={
                "club_name": club_name,
                "coordinator_id": coord_user["user_id"],
                "status": "Pending",
                "is_active": False
            },
            remarks=f"Society registration request submitted for '{club_name}' by coordinator {coord_user['name']}"
        )

    return {
        "message": f"Society registration request submitted successfully for '{club_name}'. Pending administrator approval.",
        "club_id": club_id,
        "status": "Pending",
        "coordinator": {
            "user_id": coord_user["user_id"],
            "name": coord_user["name"],
            "email": coord_user["email"]
        }
    }


@router.get("/me", response_model=UserResponse, summary="Get current logged-in user profile")
def get_me(current_user: UserContext = Depends(get_current_user), db=Depends(get_db)):
    db.execute(
        """
        SELECT u.user_id, u.department_id, u.name, u.email, u.role, u.phone_no, u.is_active,
               d.department_name
        FROM users u
        LEFT JOIN departments d ON u.department_id = d.department_id
        WHERE u.user_id = %s
        """,
        (current_user.user_id,)
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


@router.post("/change-password", summary="Change current user's password")
def change_password(
    req: ChangePasswordRequest,
    current_user: UserContext = Depends(get_current_user),
    db=Depends(get_db)
):
    """Authenticated user changes their own password with Argon2id verification."""
    db.execute("SELECT password_hash FROM users WHERE user_id = %s", (current_user.user_id,))
    row = db.fetchone()
    if not row or not verify_password(req.current_password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect."
        )

    if req.current_password == req.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password cannot be the same as the current password."
        )

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
            (new_hash, current_user.user_id)
        )
        log_system_audit(
            cursor,
            entity_type="User",
            entity_id=current_user.user_id,
            action="PasswordChange",
            changed_by=current_user.user_id,
            old_values=None,
            new_values=None,
            remarks="User successfully changed their own password."
        )

    return {
        "success": True,
        "message": "Password changed successfully. Existing sessions have been invalidated. Please sign in with your new password."
    }


@router.post("/logout", summary="Log out and invalidate session token")
def logout(current_user: UserContext = Depends(get_current_user)):
    if current_user.token:
        revoke_token(current_user.token)
    try:
        with transaction_scope() as (conn, cursor):
            cursor.execute("UPDATE users SET token_version = token_version + 1 WHERE user_id = %s", (current_user.user_id,))
    except Exception:
        pass
    return {"message": "Logged out successfully. Session token revoked."}
