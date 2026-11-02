from enum import Enum
from typing import List, Optional
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.security import decode_access_token, is_token_revoked
from app.database.dependencies import get_db

security_scheme = HTTPBearer(auto_error=False)


class Role(str, Enum):
    STUDENT = "Student"
    FACULTY = "Faculty"
    ADMIN = "Admin"
    STAFF = "Staff"


class UserContext:
    def __init__(
        self,
        user_id: int,
        email: str,
        role: str,
        name: str,
        department_id: Optional[int] = None,
        is_active: bool = True,
        token: Optional[str] = None
    ):
        self.user_id = user_id
        self.email = email
        self.role = role
        self.name = name
        self.department_id = department_id
        self.is_active = is_active
        self.token = token

    def is_admin(self) -> bool:
        return self.role == Role.ADMIN.value

    def is_faculty(self) -> bool:
        return self.role == Role.FACULTY.value

    def is_staff(self) -> bool:
        return self.role == Role.STAFF.value

    def is_student(self) -> bool:
        return self.role == Role.STUDENT.value

    def can_manage_checkins(self) -> bool:
        return self.role in (Role.ADMIN.value, Role.STAFF.value)


def get_current_user_optional(
    auth: HTTPAuthorizationCredentials = Depends(security_scheme),
    db=Depends(get_db)
) -> Optional[UserContext]:
    if not auth or not auth.credentials:
        return None

    raw_token = auth.credentials
    if is_token_revoked(raw_token):
        return None

    payload = decode_access_token(raw_token)
    if not payload or "sub" not in payload:
        return None

    try:
        user_id = int(payload.get("sub"))
    except (ValueError, TypeError):
        return None

    # Live verification of current-user and is_active in MySQL
    db.execute(
        """
        SELECT user_id, department_id, name, email, role, is_active, token_version
        FROM users
        WHERE user_id = %s
        """,
        (user_id,)
    )
    user = db.fetchone()

    if not user:
        return None

    # Persistent per-user session invalidation
    token_ver = payload.get("token_version")
    if token_ver is not None and user.get("token_version") is not None:
        if int(token_ver) != int(user["token_version"]):
            return None

    if not bool(user["is_active"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive or has been disabled. Please contact an administrator."
        )

    return UserContext(
        user_id=user["user_id"],
        email=user["email"],
        role=user["role"],
        name=user["name"],
        department_id=user["department_id"],
        is_active=bool(user["is_active"]),
        token=raw_token
    )


def get_current_user(
    current_user: Optional[UserContext] = Depends(get_current_user_optional)
) -> UserContext:
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided, are invalid, or have expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


def require_roles(*allowed_roles: Role):
    allowed_values = [r.value if isinstance(r, Role) else str(r) for r in allowed_roles]

    def role_checker(current_user: UserContext = Depends(get_current_user)) -> UserContext:
        if current_user.role not in allowed_values:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: requires one of roles {allowed_values}"
            )
        return current_user

    return role_checker
