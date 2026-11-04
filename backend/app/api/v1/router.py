from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth,
    users,
    departments,
    categories,
    resources,
    timetable,
    bookings,
    approvals,
    equipment,
    societies,
    maintenance,
    blackouts,
    equipment_blackouts,
    checkins,
    notifications,
    reports
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(departments.router, prefix="/departments", tags=["Departments"])
api_router.include_router(categories.router, prefix="/categories", tags=["Categories"])
api_router.include_router(resources.router, prefix="/resources", tags=["Resources"])
api_router.include_router(timetable.router, prefix="/timetable", tags=["Timetable & Availability"])
api_router.include_router(bookings.router, prefix="/bookings", tags=["Bookings"])
api_router.include_router(approvals.router, prefix="/approvals", tags=["Approvals"])
api_router.include_router(equipment.router, prefix="/equipment", tags=["Equipment"])
api_router.include_router(societies.router, prefix="/societies", tags=["Societies"])
api_router.include_router(maintenance.router, prefix="/maintenance", tags=["Maintenance"])
api_router.include_router(equipment_blackouts.router, prefix="/blackouts/equipment", tags=["Equipment Blackouts"])
api_router.include_router(blackouts.router, prefix="/blackouts", tags=["Blackout Management"])
api_router.include_router(checkins.router, prefix="/checkins", tags=["Check-in & Attendance"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
api_router.include_router(reports.router, prefix="/reports", tags=["Reports & Analytics"])
api_router.add_api_route("/settings", reports.get_live_settings, methods=["GET"], tags=["Settings"], summary="Get live settings alias")
api_router.add_api_route("/settings/", reports.get_live_settings, methods=["GET"], tags=["Settings"], include_in_schema=False)
