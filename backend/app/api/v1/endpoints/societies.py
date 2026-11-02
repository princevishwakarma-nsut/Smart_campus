from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.core.permissions import get_current_user, require_roles, UserContext, Role
from app.database.dependencies import get_db
from app.database.transaction import transaction_scope
from app.schemas.auth import ReviewActionRequest
from app.schemas.society import (
    SocietyCreate, SocietyUpdate, SocietyMemberAdd,
    SocietyResponse, SocietyMemberResponse
)
from app.services.audit_service import log_system_audit

router = APIRouter()


@router.get("", response_model=List[SocietyResponse], summary="List societies (Authenticated)")
def list_societies(
    status: Optional[str] = Query(None),
    current_user: UserContext = Depends(get_current_user),
    db=Depends(get_db)
):
    query = """
        SELECT s.club_id, s.department_id, s.club_name, s.description,
               s.faculty_coordinator_id, s.created_by, s.established_year, s.is_active,
               s.status, s.rejection_reason, s.reviewed_by, s.reviewed_at, s.created_at,
               d.department_name, u.name as faculty_coordinator_name,
               (SELECT COUNT(*) FROM society_members sm WHERE sm.club_id = s.club_id AND sm.is_active = 1) as members_count
        FROM societies s
        LEFT JOIN departments d ON s.department_id = d.department_id
        LEFT JOIN users u ON s.faculty_coordinator_id = u.user_id
        WHERE 1=1
    """
    params = []

    # Non-admins only see active, approved societies
    if not current_user.is_admin():
        query += " AND s.is_active = 1 AND s.status = 'Approved'"
    else:
        if status and status != "All":
            query += " AND s.status = %s"
            params.append(status)

    query += " ORDER BY s.club_name ASC"
    db.execute(query, tuple(params))
    rows = db.fetchall()

    return [
        SocietyResponse(
            club_id=r["club_id"],
            club_name=r["club_name"],
            department_id=r["department_id"],
            department_name=r["department_name"],
            description=r["description"],
            faculty_coordinator_id=r["faculty_coordinator_id"],
            faculty_coordinator_name=r["faculty_coordinator_name"],
            created_by=r["created_by"],
            established_year=r["established_year"],
            is_active=bool(r["is_active"]),
            status=r.get("status") or ("Approved" if r["is_active"] else "Pending"),
            rejection_reason=r.get("rejection_reason"),
            reviewed_by=r.get("reviewed_by"),
            reviewed_at=r.get("reviewed_at"),
            members_count=r["members_count"],
            created_at=r["created_at"]
        )
        for r in rows
    ]


@router.get("/{club_id}", response_model=SocietyResponse, summary="Get society details")
def get_society(club_id: int, current_user: UserContext = Depends(get_current_user), db=Depends(get_db)):
    query = """
        SELECT s.club_id, s.department_id, s.club_name, s.description,
               s.faculty_coordinator_id, s.created_by, s.established_year, s.is_active,
               s.status, s.rejection_reason, s.reviewed_by, s.reviewed_at, s.created_at,
               d.department_name, u.name as faculty_coordinator_name,
               (SELECT COUNT(*) FROM society_members sm WHERE sm.club_id = s.club_id AND sm.is_active = 1) as members_count
        FROM societies s
        LEFT JOIN departments d ON s.department_id = d.department_id
        LEFT JOIN users u ON s.faculty_coordinator_id = u.user_id
        WHERE s.club_id = %s
    """
    db.execute(query, (club_id,))
    row = db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Society not found")

    return SocietyResponse(
        club_id=row["club_id"],
        club_name=row["club_name"],
        department_id=row["department_id"],
        department_name=row["department_name"],
        description=row["description"],
        faculty_coordinator_id=row["faculty_coordinator_id"],
        faculty_coordinator_name=row["faculty_coordinator_name"],
        created_by=row["created_by"],
        established_year=row["established_year"],
        is_active=bool(row["is_active"]),
        status=row.get("status") or ("Approved" if row["is_active"] else "Pending"),
        rejection_reason=row.get("rejection_reason"),
        reviewed_by=row.get("reviewed_by"),
        reviewed_at=row.get("reviewed_at"),
        members_count=row["members_count"],
        created_at=row["created_at"]
    )


@router.post("/{club_id}/approve", response_model=SocietyResponse, summary="Approve society registration (Admin only)")
def approve_society(
    club_id: int,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    db.execute("SELECT * FROM societies WHERE club_id = %s", (club_id,))
    society = db.fetchone()
    if not society:
        raise HTTPException(status_code=404, detail="Society not found.")

    with transaction_scope() as (conn, cursor):
        cursor.execute(
            """
            UPDATE societies
            SET status = 'Approved', is_active = 1, reviewed_by = %s, reviewed_at = CURRENT_TIMESTAMP
            WHERE club_id = %s
            """,
            (current_user.user_id, club_id)
        )

        log_system_audit(
            cursor,
            entity_type="Society",
            entity_id=club_id,
            action="Approved",
            changed_by=current_user.user_id,
            old_values={"status": society.get("status"), "is_active": society["is_active"]},
            new_values={"status": "Approved", "is_active": 1},
            remarks=f"Society '{society['club_name']}' approved by Admin {current_user.name}"
        )

        # Send notification to society creator/coordinator
        if society["created_by"]:
            cursor.execute(
                """
                INSERT INTO notifications (user_id, message, type, is_read)
                VALUES (%s, %s, 'Approval', 0)
                """,
                (
                    society["created_by"],
                    f"Your registration for society '{society['club_name']}' has been approved by the campus administrator. It is now active for space bookings."
                )
            )

    return get_society(club_id, current_user, db)


@router.post("/{club_id}/reject", response_model=SocietyResponse, summary="Reject society registration (Admin only)")
def reject_society(
    club_id: int,
    req: ReviewActionRequest,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    db.execute("SELECT * FROM societies WHERE club_id = %s", (club_id,))
    society = db.fetchone()
    if not society:
        raise HTTPException(status_code=404, detail="Society not found.")

    reason = req.reason.strip() if req.reason else "Society details could not be verified."

    with transaction_scope() as (conn, cursor):
        cursor.execute(
            """
            UPDATE societies
            SET status = 'Rejected', is_active = 0, rejection_reason = %s, reviewed_by = %s, reviewed_at = CURRENT_TIMESTAMP
            WHERE club_id = %s
            """,
            (reason, current_user.user_id, club_id)
        )

        log_system_audit(
            cursor,
            entity_type="Society",
            entity_id=club_id,
            action="Rejected",
            changed_by=current_user.user_id,
            old_values={"status": society.get("status"), "is_active": society["is_active"]},
            new_values={"status": "Rejected", "is_active": 0, "reason": reason},
            remarks=f"Society '{society['club_name']}' rejected by Admin {current_user.name}: {reason}"
        )

        if society["created_by"]:
            cursor.execute(
                """
                INSERT INTO notifications (user_id, message, type, is_read)
                VALUES (%s, %s, 'Alert', 0)
                """,
                (
                    society["created_by"],
                    f"Registration for society '{society['club_name']}' was rejected: {reason}"
                )
            )

    return get_society(club_id, current_user, db)



@router.post("", response_model=SocietyResponse, status_code=status.HTTP_201_CREATED, summary="Create society (Admin)")
def create_society(
    req: SocietyCreate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    db.execute("SELECT club_id FROM societies WHERE club_name = %s", (req.club_name.strip(),))
    if db.fetchone():
        raise HTTPException(status_code=400, detail="Society with this name already exists.")

    with transaction_scope() as (conn, cursor):
        cursor.execute(
            """
            INSERT INTO societies (department_id, club_name, description, faculty_coordinator_id, created_by, established_year, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, 1)
            """,
            (
                req.department_id,
                req.club_name.strip(),
                req.description,
                req.faculty_coordinator_id,
                current_user.user_id,
                req.established_year
            )
        )
        club_id = cursor.lastrowid

        log_system_audit(
            cursor,
            entity_type="Society",
            entity_id=club_id,
            action="Created",
            changed_by=current_user.user_id,
            old_values=None,
            new_values={"club_name": req.club_name.strip()},
            remarks=f"Society registered by Admin {current_user.name}"
        )

    return get_society(club_id, current_user, db)


@router.put("/{club_id}", response_model=SocietyResponse, summary="Edit society (Admin)")
def update_society(
    club_id: int,
    req: SocietyUpdate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    updates = []
    params = []
    if req.club_name is not None:
        updates.append("club_name = %s")
        params.append(req.club_name.strip())
    if req.department_id is not None:
        updates.append("department_id = %s")
        params.append(req.department_id)
    if req.description is not None:
        updates.append("description = %s")
        params.append(req.description)
    if req.faculty_coordinator_id is not None:
        updates.append("faculty_coordinator_id = %s")
        params.append(req.faculty_coordinator_id)
    if req.established_year is not None:
        updates.append("established_year = %s")
        params.append(req.established_year)
    if req.is_active is not None:
        updates.append("is_active = %s")
        params.append(1 if req.is_active else 0)

    if updates:
        with transaction_scope() as (conn, cursor):
            params.append(club_id)
            cursor.execute(f"UPDATE societies SET {', '.join(updates)} WHERE club_id = %s", tuple(params))
            log_system_audit(
                cursor,
                entity_type="Society",
                entity_id=club_id,
                action="Updated",
                changed_by=current_user.user_id,
                old_values=None,
                new_values=req.model_dump(exclude_unset=True),
                remarks=f"Society updated by {current_user.name}"
            )

    return get_society(club_id, current_user, db)


@router.get("/{club_id}/members", response_model=List[SocietyMemberResponse], summary="Get society members (Protected)")
def get_society_members(club_id: int, current_user: UserContext = Depends(get_current_user), db=Depends(get_db)):
    query = """
        SELECT sm.club_member_id, sm.club_id, sm.user_id, sm.member_role,
               sm.can_manage, sm.can_book, sm.joined_at, sm.is_active,
               u.name as user_name, u.email as user_email
        FROM society_members sm
        JOIN users u ON sm.user_id = u.user_id
        WHERE sm.club_id = %s AND sm.is_active = 1
        ORDER BY sm.member_role ASC, u.name ASC
    """
    db.execute(query, (club_id,))
    rows = db.fetchall()

    return [
        SocietyMemberResponse(
            club_member_id=r["club_member_id"],
            club_id=r["club_id"],
            user_id=r["user_id"],
            user_name=r["user_name"],
            user_email=r["user_email"],
            member_role=r["member_role"],
            can_manage=bool(r["can_manage"]),
            can_book=bool(r["can_book"]),
            is_active=bool(r["is_active"]),
            joined_at=r["joined_at"]
        )
        for r in rows
    ]


@router.post("/{club_id}/members", response_model=SocietyMemberResponse, status_code=status.HTTP_201_CREATED, summary="Add member to society")
def add_society_member(
    club_id: int,
    req: SocietyMemberAdd,
    current_user: UserContext = Depends(get_current_user),
    db=Depends(get_db)
):
    # Only Admin or member with can_manage can add members
    if not current_user.is_admin():
        db.execute(
            "SELECT can_manage FROM society_members WHERE club_id = %s AND user_id = %s AND is_active = 1",
            (club_id, current_user.user_id)
        )
        member = db.fetchone()
        if not member or not member["can_manage"]:
            raise HTTPException(status_code=403, detail="Not authorized to manage members of this society.")

        # A non-admin cannot grant can_manage permission to others (prevents privilege escalation)
        if req.can_manage:
            raise HTTPException(status_code=403, detail="Only administrators can grant administrative (can_manage) permission.")

    # Check if user exists
    db.execute("SELECT user_id, name, is_active FROM users WHERE user_id = %s", (req.user_id,))
    target_user = db.fetchone()
    if not target_user or not target_user["is_active"]:
        raise HTTPException(status_code=400, detail="Target user does not exist or is inactive.")

    with transaction_scope() as (conn, cursor):
        # Check if already a member
        cursor.execute("SELECT club_member_id, is_active FROM society_members WHERE club_id = %s AND user_id = %s", (club_id, req.user_id))
        existing = cursor.fetchone()
        if existing:
            if existing["is_active"]:
                raise HTTPException(status_code=400, detail="User is already an active member of this society.")
            cursor.execute(
                """
                UPDATE society_members
                SET is_active = 1, member_role = %s, can_manage = %s, can_book = %s
                WHERE club_member_id = %s
                """,
                (req.member_role, 1 if req.can_manage else 0, 1 if req.can_book else 0, existing["club_member_id"])
            )
            cm_id = existing["club_member_id"]
        else:
            cursor.execute(
                """
                INSERT INTO society_members (club_id, user_id, member_role, can_manage, can_book, is_active)
                VALUES (%s, %s, %s, %s, %s, 1)
                """,
                (club_id, req.user_id, req.member_role, 1 if req.can_manage else 0, 1 if req.can_book else 0)
            )
            cm_id = cursor.lastrowid

        log_system_audit(
            cursor,
            entity_type="SocietyMember",
            entity_id=cm_id,
            action="MemberAdded",
            changed_by=current_user.user_id,
            old_values=None,
            new_values={"club_id": club_id, "user_id": req.user_id, "role": req.member_role},
            remarks=f"User {target_user['name']} added to society by {current_user.name}"
        )

    query = """
        SELECT sm.club_member_id, sm.club_id, sm.user_id, sm.member_role,
               sm.can_manage, sm.can_book, sm.joined_at, sm.is_active,
               u.name as user_name, u.email as user_email
        FROM society_members sm
        JOIN users u ON sm.user_id = u.user_id
        WHERE sm.club_member_id = %s
    """
    db.execute(query, (cm_id,))
    r = db.fetchone()

    return SocietyMemberResponse(
        club_member_id=r["club_member_id"],
        club_id=r["club_id"],
        user_id=r["user_id"],
        user_name=r["user_name"],
        user_email=r["user_email"],
        member_role=r["member_role"],
        can_manage=bool(r["can_manage"]),
        can_book=bool(r["can_book"]),
        is_active=bool(r["is_active"]),
        joined_at=r["joined_at"]
    )


@router.delete("/{club_id}/members/{user_id}", summary="Remove member from society")
def remove_society_member(
    club_id: int,
    user_id: int,
    current_user: UserContext = Depends(get_current_user),
    db=Depends(get_db)
):
    if not current_user.is_admin():
        db.execute(
            "SELECT can_manage FROM society_members WHERE club_id = %s AND user_id = %s AND is_active = 1",
            (club_id, current_user.user_id)
        )
        member = db.fetchone()
        if not member or not member["can_manage"]:
            raise HTTPException(status_code=403, detail="Not authorized to remove members from this society.")

    with transaction_scope() as (conn, cursor):
        cursor.execute(
            "UPDATE society_members SET is_active = 0 WHERE club_id = %s AND user_id = %s",
            (club_id, user_id)
        )
        log_system_audit(
            cursor,
            entity_type="SocietyMember",
            entity_id=club_id,
            action="MemberRemoved",
            changed_by=current_user.user_id,
            old_values=None,
            new_values={"user_id": user_id},
            remarks=f"Member ID {user_id} removed by {current_user.name}"
        )

    return {"message": "Member removed successfully from society."}
