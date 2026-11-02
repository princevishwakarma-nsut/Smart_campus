from typing import List, Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.core.config import settings
from app.core.permissions import get_current_user, require_roles, UserContext, Role
from app.database.dependencies import get_db
from app.database.transaction import transaction_scope
from app.schemas.timetable import (
    TimetableResponse, AvailabilityResponse,
    AssignFacultyRequest, FacultyUserOption
)
from app.services.audit_service import log_system_audit
from app.services.availability import check_resource_availability, get_resource_schedule_for_day

router = APIRouter()


@router.get("/my", response_model=List[TimetableResponse], summary="Get logged-in faculty teaching timetable")
def get_my_timetable(
    day_of_week: Optional[str] = Query(None, description="Monday, Tuesday, etc."),
    semester: Optional[str] = Query(None),
    academic_year: Optional[str] = Query(None),
    current_user: UserContext = Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Returns only the teaching timetable entries assigned to the authenticated Faculty member.
    Does not allow passing arbitrary faculty_user_id or viewing other faculty schedules.
    """
    if not (current_user.is_faculty() or current_user.is_admin()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only faculty members can access personal teaching timetables."
        )

    query = """
        SELECT t.timetable_id, t.resource_id, t.department_name, t.section, t.subject_name,
               t.day_of_week, t.start_time, t.end_time, t.academic_year, t.semester, t.class_type,
               r.resource_name,
               u.user_id as fac_id, u.name as fac_name, u.email as fac_email
        FROM timetable_faculty_assignments tfa
        JOIN resource_timetable t ON tfa.timetable_id = t.timetable_id
        JOIN resources r ON t.resource_id = r.resource_id
        JOIN users u ON tfa.faculty_user_id = u.user_id
        WHERE tfa.faculty_user_id = %s
    """
    params = [current_user.user_id]

    if day_of_week:
        query += " AND t.day_of_week = %s"
        params.append(day_of_week)

    if semester:
        query += " AND t.semester = %s"
        params.append(semester)

    if academic_year:
        query += " AND t.academic_year = %s"
        params.append(academic_year)
    elif hasattr(settings, "CURRENT_ACADEMIC_YEAR") and settings.CURRENT_ACADEMIC_YEAR:
        query += " AND (t.academic_year = %s OR t.academic_year IS NULL)"
        params.append(settings.CURRENT_ACADEMIC_YEAR)

    query += " ORDER BY FIELD(t.day_of_week, 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'), t.start_time ASC"

    db.execute(query, tuple(params))
    rows = db.fetchall()

    return [
        TimetableResponse(
            timetable_id=r["timetable_id"],
            resource_id=r["resource_id"],
            resource_name=r["resource_name"],
            department_name=r["department_name"],
            section=r["section"],
            subject_name=r["subject_name"],
            day_of_week=r["day_of_week"],
            start_time=str(r["start_time"]),
            end_time=str(r["end_time"]),
            academic_year=r["academic_year"],
            semester=r["semester"],
            class_type=r["class_type"],
            assigned_faculty=[{"user_id": r["fac_id"], "name": r["fac_name"], "email": r["fac_email"]}]
        )
        for r in rows
    ]


@router.get("/faculty-users", response_model=List[FacultyUserOption], summary="List active faculty users for assignment (Admin only)")
def list_faculty_users(
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    query = """
        SELECT u.user_id, u.name, u.email, u.is_active, d.department_name
        FROM users u
        LEFT JOIN departments d ON u.department_id = d.department_id
        WHERE u.role = 'Faculty' AND u.is_active = 1
        ORDER BY u.name ASC
    """
    db.execute(query)
    return [
        FacultyUserOption(
            user_id=r["user_id"],
            name=r["name"],
            email=r["email"],
            department_name=r["department_name"],
            is_active=bool(r["is_active"])
        )
        for r in db.fetchall()
    ]


@router.get("/assignments", response_model=List[TimetableResponse], summary="List timetable entries with faculty assignments (Admin only)")
def list_timetable_assignments(
    department_name: Optional[str] = Query(None),
    section: Optional[str] = Query(None),
    semester: Optional[str] = Query(None),
    subject: Optional[str] = Query(None),
    unassigned_only: bool = Query(False),
    faculty_user_id: Optional[int] = Query(None),
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    query = """
        SELECT t.timetable_id, t.resource_id, t.department_name, t.section, t.subject_name,
               t.day_of_week, t.start_time, t.end_time, t.academic_year, t.semester, t.class_type,
               r.resource_name
        FROM resource_timetable t
        JOIN resources r ON t.resource_id = r.resource_id
        WHERE 1=1
    """
    params = []
    if department_name:
        query += " AND t.department_name = %s"
        params.append(department_name)
    if section:
        query += " AND t.section = %s"
        params.append(section)
    if semester:
        query += " AND t.semester = %s"
        params.append(semester)
    if subject:
        query += " AND t.subject_name LIKE %s"
        params.append(f"%{subject.strip()}%")

    query += " ORDER BY t.department_name, t.section, FIELD(t.day_of_week, 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'), t.start_time ASC LIMIT 600"
    db.execute(query, tuple(params))
    rows = db.fetchall()

    if not rows:
        return []

    # Fetch assignments map
    tt_ids = [r["timetable_id"] for r in rows]
    format_strings = ','.join(['%s'] * len(tt_ids))
    asgn_query = f"""
        SELECT tfa.timetable_id, u.user_id, u.name, u.email
        FROM timetable_faculty_assignments tfa
        JOIN users u ON tfa.faculty_user_id = u.user_id
        WHERE tfa.timetable_id IN ({format_strings})
    """
    db.execute(asgn_query, tuple(tt_ids))
    asgns = db.fetchall()
    asgn_map = {}
    for a in asgns:
        asgn_map.setdefault(a["timetable_id"], []).append({
            "user_id": a["user_id"],
            "name": a["name"],
            "email": a["email"]
        })

    result = []
    for r in rows:
        tid = r["timetable_id"]
        assigned = asgn_map.get(tid, [])
        if unassigned_only and len(assigned) > 0:
            continue
        if faculty_user_id and not any(f["user_id"] == faculty_user_id for f in assigned):
            continue

        result.append(
            TimetableResponse(
                timetable_id=tid,
                resource_id=r["resource_id"],
                resource_name=r["resource_name"],
                department_name=r["department_name"],
                section=r["section"],
                subject_name=r["subject_name"],
                day_of_week=r["day_of_week"],
                start_time=str(r["start_time"]),
                end_time=str(r["end_time"]),
                academic_year=r["academic_year"],
                semester=r["semester"],
                class_type=r["class_type"],
                assigned_faculty=assigned
            )
        )

    return result


@router.post("/{timetable_id}/assign", summary="Assign one or more faculty members to timetable entry (Admin only)")
def assign_faculty_to_timetable(
    timetable_id: int,
    req: AssignFacultyRequest,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    db.execute("SELECT * FROM resource_timetable WHERE timetable_id = %s", (timetable_id,))
    tt_entry = db.fetchone()
    if not tt_entry:
        raise HTTPException(status_code=404, detail="Timetable entry not found.")

    # Validate all faculty user IDs belong to active faculty
    f_ids = req.faculty_user_ids or ([req.faculty_user_id] if req.faculty_user_id else [])
    if not f_ids:
        raise HTTPException(status_code=400, detail="At least one faculty user ID must be provided.")

    for f_id in f_ids:
        db.execute("SELECT user_id, name, role, is_active FROM users WHERE user_id = %s", (f_id,))
        u = db.fetchone()
        if not u or u["role"] != "Faculty" or not u["is_active"]:
            raise HTTPException(
                status_code=400,
                detail=f"User ID {f_id} is not an active Faculty member."
            )

    assigned_names = []
    with transaction_scope() as (conn, cursor):
        for f_id in f_ids:
            cursor.execute(
                """
                INSERT IGNORE INTO timetable_faculty_assignments (timetable_id, faculty_user_id, assigned_by)
                VALUES (%s, %s, %s)
                """,
                (timetable_id, f_id, current_user.user_id)
            )
            cursor.execute("SELECT name FROM users WHERE user_id = %s", (f_id,))
            name_row = cursor.fetchone()
            if name_row:
                assigned_names.append(name_row["name"])

        log_system_audit(
            cursor,
            entity_type="TimetableAssignment",
            entity_id=timetable_id,
            action="Assigned",
            changed_by=current_user.user_id,
            old_values=None,
            new_values={"timetable_id": timetable_id, "faculty_user_ids": req.faculty_user_ids},
            remarks=f"Assigned faculty [{', '.join(assigned_names)}] to {tt_entry['subject_name']} ({tt_entry['section']})"
        )

    return {
        "success": True,
        "message": f"Successfully assigned faculty to {tt_entry['subject_name']}.",
        "timetable_id": timetable_id,
        "assigned_faculty_count": len(f_ids)
    }


@router.delete("/{timetable_id}/assignments/{faculty_user_id}", summary="Remove a faculty assignment (Admin only)")
def remove_faculty_assignment(
    timetable_id: int,
    faculty_user_id: int,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    db.execute(
        "SELECT * FROM timetable_faculty_assignments WHERE timetable_id = %s AND faculty_user_id = %s",
        (timetable_id, faculty_user_id)
    )
    asgn = db.fetchone()
    if not asgn:
        raise HTTPException(status_code=404, detail="Faculty assignment not found.")

    with transaction_scope() as (conn, cursor):
        cursor.execute(
            "DELETE FROM timetable_faculty_assignments WHERE timetable_id = %s AND faculty_user_id = %s",
            (timetable_id, faculty_user_id)
        )
        log_system_audit(
            cursor,
            entity_type="TimetableAssignment",
            entity_id=timetable_id,
            action="Unassigned",
            changed_by=current_user.user_id,
            old_values={"faculty_user_id": faculty_user_id},
            new_values=None,
            remarks=f"Removed faculty user {faculty_user_id} assignment from timetable entry {timetable_id}"
        )

    return {"message": "Assignment removed successfully.", "timetable_id": timetable_id, "faculty_user_id": faculty_user_id}


@router.get("", response_model=List[TimetableResponse], summary="List recurring academic timetable")
def list_timetable(
    department_name: Optional[str] = Query(None),
    section: Optional[str] = Query(None),
    day_of_week: Optional[str] = Query(None),
    semester: Optional[str] = Query(None),
    resource_id: Optional[int] = Query(None),
    db=Depends(get_db)
):
    query = """
        SELECT t.timetable_id, t.resource_id, t.department_name, t.section, t.subject_name,
               t.day_of_week, t.start_time, t.end_time, t.academic_year, t.semester, t.class_type,
               r.resource_name
        FROM resource_timetable t
        JOIN resources r ON t.resource_id = r.resource_id
        WHERE 1=1
    """
    params = []
    if department_name:
        query += " AND t.department_name = %s"
        params.append(department_name)
    if section:
        query += " AND t.section = %s"
        params.append(section)
    if day_of_week:
        query += " AND t.day_of_week = %s"
        params.append(day_of_week)
    if semester:
        query += " AND t.semester = %s"
        params.append(semester)
    if resource_id:
        query += " AND t.resource_id = %s"
        params.append(resource_id)

    query += " ORDER BY t.day_of_week, t.start_time ASC LIMIT 500"
    db.execute(query, tuple(params))
    rows = db.fetchall()

    return [
        TimetableResponse(
            timetable_id=r["timetable_id"],
            resource_id=r["resource_id"],
            resource_name=r["resource_name"],
            department_name=r["department_name"],
            section=r["section"],
            subject_name=r["subject_name"],
            day_of_week=r["day_of_week"],
            start_time=str(r["start_time"]),
            end_time=str(r["end_time"]),
            academic_year=r["academic_year"],
            semester=r["semester"],
            class_type=r["class_type"]
        )
        for r in rows
    ]


@router.get("/resource/{resource_id}", summary="Get timetable & bookings schedule for a resource")
def get_resource_timetable(
    resource_id: int,
    date_str: Optional[str] = Query(None, alias="date", description="YYYY-MM-DD"),
    db=Depends(get_db)
):
    target_date = date.fromisoformat(date_str) if date_str else date.today()
    schedule = get_resource_schedule_for_day(db, resource_id, target_date)
    return schedule


@router.get("/section", response_model=List[TimetableResponse], summary="Get timetable for a specific department and section")
def get_section_timetable(
    department_name: str = Query(..., description="CSE, CSAI, CSDS, MAC"),
    section: str = Query(..., description="e.g. Sec-1"),
    db=Depends(get_db)
):
    return list_timetable(department_name=department_name, section=section, db=db)


@router.get("/check", response_model=AvailabilityResponse, summary="Check single resource slot availability")
def check_availability(
    resource_id: int = Query(...),
    start_time: str = Query(..., description="ISO 8601 string, e.g. 2026-11-03T10:00:00"),
    end_time: str = Query(..., description="ISO 8601 string, e.g. 2026-11-03T12:00:00"),
    exclude_booking_id: Optional[int] = Query(None),
    db=Depends(get_db)
):
    try:
        start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00")).replace(tzinfo=None)
        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date/time format. Use ISO format YYYY-MM-DDTHH:MM:SS.")

    if end_dt <= start_dt:
        return AvailabilityResponse(is_available=False, state="blocked", reason="End time must be after start time.")

    res = check_resource_availability(db, resource_id, start_dt, end_dt, exclude_booking_id=exclude_booking_id)
    return AvailabilityResponse(**res)


@router.get("/search-available", summary="Find all resources available for selected date/time")
def search_available_resources(
    start_time: str = Query(...),
    end_time: str = Query(...),
    category_id: Optional[int] = Query(None),
    min_capacity: Optional[int] = Query(None),
    db=Depends(get_db)
):
    try:
        start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00")).replace(tzinfo=None)
        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date/time format.")

    query = "SELECT resource_id, resource_name, resource_code, location, capacity, status, category_id FROM resources WHERE status = 'Available'"
    params = []
    if category_id:
        query += " AND category_id = %s"
        params.append(category_id)
    if min_capacity:
        query += " AND capacity >= %s"
        params.append(min_capacity)

    db.execute(query, tuple(params))
    resources = db.fetchall()

    available = []
    for r in resources:
        status_check = check_resource_availability(db, r["resource_id"], start_dt, end_dt)
        if status_check["is_available"]:
            available.append(r)

    return available
