from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.core.permissions import require_roles, get_current_user, UserContext, Role
from app.database.dependencies import get_db
from app.database.transaction import transaction_scope
from app.schemas.equipment import (
    EquipmentCreate, EquipmentUpdate, EquipmentStatusUpdate,
    EquipmentStockAdjustRequest, EquipmentIssueQuantityRequest,
    EquipmentReturnQuantityRequest, EquipmentResponse,
    EquipmentStockMovementResponse, EquipmentSummaryResponse
)
from app.services.equipment_availability import (
    calculate_equipment_availability,
    get_all_equipment_with_availability
)
from app.services.audit_service import log_system_audit

router = APIRouter()


@router.get("", response_model=List[EquipmentResponse], summary="List equipment items with dynamic availability")
def list_equipment(
    category: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    q: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    current_user: Optional[UserContext] = Depends(get_current_user),
    db=Depends(get_db)
):
    start_dt = None
    end_dt = None
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass

    # Non-admins only see active equipment by default
    active_filter = is_active
    if current_user and not (current_user.is_admin() or current_user.is_staff()) and active_filter is None:
        active_filter = True

    items = get_all_equipment_with_availability(
        cursor=db,
        start_dt=start_dt,
        end_dt=end_dt,
        category=category,
        location=location,
        is_active=active_filter,
        q=q
    )
    return [EquipmentResponse.model_validate(it) for it in items]


@router.get("/dashboard/summary", response_model=EquipmentSummaryResponse, summary="Get equipment inventory summary (Admin/Staff)")
def get_equipment_summary(
    current_user: UserContext = Depends(require_roles(Role.ADMIN, Role.STAFF)),
    db=Depends(get_db)
):
    db.execute("""
        SELECT
            COUNT(*) as total_types,
            COALESCE(SUM(total_quantity), 0) as total_units,
            COALESCE(SUM(damaged_quantity), 0) as damaged_units,
            COALESCE(SUM(maintenance_quantity), 0) as maintenance_units,
            COALESCE(SUM(lost_quantity), 0) as lost_units
        FROM equipment_items
        WHERE is_active = 1
    """)
    totals = db.fetchone()

    # Calculate current overall available and reserved
    all_items = get_all_equipment_with_availability(db, is_active=True)
    avail_sum = sum(it.get("available_quantity", 0) for it in all_items)
    res_sum = sum(it.get("reserved_quantity", 0) for it in all_items)

    db.execute("""
        SELECT category, COUNT(*) as type_count, SUM(total_quantity) as total_units
        FROM equipment_items
        WHERE is_active = 1
        GROUP BY category
        ORDER BY category ASC
    """)
    cat_rows = db.fetchall()

    return EquipmentSummaryResponse(
        total_types=totals["total_types"],
        total_units=totals["total_units"],
        available_units=avail_sum,
        reserved_units=res_sum,
        damaged_units=totals["damaged_units"],
        maintenance_units=totals["maintenance_units"],
        lost_units=totals["lost_units"],
        categories=[dict(r) for r in cat_rows]
    )


@router.get("/{item_id}", response_model=EquipmentResponse, summary="Get equipment item with dynamic availability")
def get_equipment(
    item_id: int,
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    db=Depends(get_db)
):
    start_dt = datetime.now()
    end_dt = start_dt.replace(hour=(start_dt.hour + 2) % 24)
    if isinstance(start_time, str) and start_time.strip():
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    if isinstance(end_time, str) and end_time.strip():
        try:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass

    avail = calculate_equipment_availability(db, item_id, start_dt, end_dt)
    if not avail:
        raise HTTPException(status_code=404, detail="Equipment item not found.")

    db.execute("SELECT description, location, purchase_date, created_at, updated_at, availability_status, condition_status FROM equipment_items WHERE item_id = %s", (item_id,))
    meta = db.fetchone()
    avail.update(meta)
    current_availability = (avail.get("availability_status") or "Available").strip()
    cond = avail.get("condition_status") or ("Damaged" if avail.get("damaged_quantity", 0) > 0 else "Good")
    if current_availability == "Issued":
        avail_status = "Issued"
    elif current_availability == "Maintenance" or avail.get("maintenance_quantity", 0) > 0 or avail.get("damaged_quantity", 0) > 0:
        avail_status = "Maintenance"
    else:
        avail_status = "Available"
    avail["condition_status"] = cond
    avail["availability_status"] = avail_status
    return EquipmentResponse.model_validate(avail)


@router.get("/{item_id}/availability", summary="Check dynamic availability for specific time window")
def check_item_availability(
    item_id: int,
    start_time: str = Query(..., description="ISO 8601 start time"),
    end_time: str = Query(..., description="ISO 8601 end time"),
    db=Depends(get_db)
):
    try:
        start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00")).replace(tzinfo=None)
        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date/time format. Use ISO 8601.")

    if end_dt <= start_dt:
        raise HTTPException(status_code=400, detail="End time must be after start time.")

    avail = calculate_equipment_availability(db, item_id, start_dt, end_dt)
    if not avail:
        raise HTTPException(status_code=404, detail="Equipment item not found.")

    return avail


@router.post("", response_model=EquipmentResponse, status_code=status.HTTP_201_CREATED, summary="Add new equipment item (Admin only)")
def create_equipment(
    req: EquipmentCreate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    item_code = req.get_code()
    db.execute("SELECT item_id FROM equipment_items WHERE item_code = %s", (item_code,))
    if db.fetchone():
        raise HTTPException(status_code=400, detail=f"Equipment with code '{item_code}' already exists.")

    with transaction_scope() as (conn, cursor):
        cursor.execute(
            """
            INSERT INTO equipment_items (
                item_code, item_name, category, description, unit,
                total_quantity, damaged_quantity, maintenance_quantity, lost_quantity,
                location, purchase_date, is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s, 0, 0, 0, %s, %s, 1)
            """,
            (
                item_code,
                req.item_name.strip(),
                req.category,
                req.description.strip() if req.description else None,
                req.unit.strip() if req.unit else "Piece",
                req.total_quantity,
                req.location.strip() if req.location else "Gym",
                req.purchase_date
            )
        )
        item_id = cursor.lastrowid

        # Record initial stock addition movement
        cursor.execute(
            """
            INSERT INTO equipment_stock_movements (item_id, movement_type, quantity, user_id, notes)
            VALUES (%s, 'Stock Added', %s, %s, %s)
            """,
            (item_id, req.total_quantity, current_user.user_id, f"Initial inventory addition for {req.item_name.strip()}")
        )

        log_system_audit(
            cursor,
            entity_type="Equipment",
            entity_id=item_id,
            action="Created",
            changed_by=current_user.user_id,
            old_values=None,
            new_values={"item_code": item_code, "item_name": req.item_name.strip(), "total_quantity": req.total_quantity},
            remarks=f"Equipment item '{req.item_name.strip()}' added by Admin {current_user.name}"
        )

    return get_equipment(item_id, db=db)


@router.put("/{item_id}", response_model=EquipmentResponse, summary="Edit equipment item details (Admin only)")
def update_equipment(
    item_id: int,
    req: EquipmentUpdate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    db.execute("SELECT * FROM equipment_items WHERE item_id = %s", (item_id,))
    eq = db.fetchone()
    if not eq:
        raise HTTPException(status_code=404, detail="Equipment item not found.")

    updates = []
    params = []
    if req.item_name is not None:
        updates.append("item_name = %s")
        params.append(req.item_name.strip())
    if req.category is not None:
        updates.append("category = %s")
        params.append(req.category)
    if req.description is not None:
        updates.append("description = %s")
        params.append(req.description.strip())
    if req.unit is not None:
        updates.append("unit = %s")
        params.append(req.unit.strip())
    if req.location is not None:
        updates.append("location = %s")
        params.append(req.location.strip())
    if req.purchase_date is not None:
        updates.append("purchase_date = %s")
        params.append(req.purchase_date)
    if req.is_active is not None:
        updates.append("is_active = %s")
        params.append(1 if req.is_active else 0)

    if updates:
        with transaction_scope() as (conn, cursor):
            params.append(item_id)
            cursor.execute(f"UPDATE equipment_items SET {', '.join(updates)} WHERE item_id = %s", tuple(params))

            log_system_audit(
                cursor,
                entity_type="Equipment",
                entity_id=item_id,
                action="Updated",
                changed_by=current_user.user_id,
                old_values={"item_name": eq["item_name"], "category": eq["category"]},
                new_values=req.model_dump(exclude_unset=True),
                remarks=f"Equipment details edited by Admin {current_user.name}"
            )

    return get_equipment(item_id, db=db)


@router.patch("/{item_id}/stock", summary="Adjust inventory quantities (Admin only)")
@router.post("/{item_id}/stock", summary="Adjust inventory quantities alias (Admin only)", include_in_schema=False)
def adjust_equipment_stock(
    item_id: int,
    req: EquipmentStockAdjustRequest,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    with transaction_scope() as (conn, cursor):
        cursor.execute("SELECT * FROM equipment_items WHERE item_id = %s FOR UPDATE", (item_id,))
        eq = cursor.fetchone()
        if not eq:
            raise HTTPException(status_code=404, detail="Equipment item not found.")

        qty = req.quantity
        action = req.get_action()
        movement_type = "Stock Adjustment"
        notes = req.notes or f"Stock adjustment: {action}"

        total = eq["total_quantity"]
        damaged = eq["damaged_quantity"]
        maint = eq["maintenance_quantity"]
        lost = eq["lost_quantity"]

        if action == "add":
            total += qty
            movement_type = "Stock Added"
            notes = req.notes or f"Added {qty} units to physical inventory"
        elif action == "damage":
            usable = total - damaged - maint - lost
            if qty > usable:
                raise HTTPException(status_code=400, detail=f"Cannot mark {qty} units as damaged. Only {usable} usable units in stock.")
            damaged += qty
            movement_type = "Returned Damaged"
            notes = req.notes or f"Recorded {qty} damaged units"
        elif action == "maintenance":
            # Move damaged or uninspected items into maintenance
            if damaged >= qty:
                damaged -= qty
            maint += qty
            movement_type = "Moved to Maintenance"
            notes = req.notes or f"Moved {qty} units to maintenance workshop"
        elif action == "repair":
            if qty > maint:
                raise HTTPException(status_code=400, detail=f"Cannot repair {qty} units. Only {maint} units currently under maintenance.")
            maint -= qty
            movement_type = "Repaired"
            notes = req.notes or f"Inspected and returned {qty} repaired units to usable stock"
        elif action == "lost":
            usable = total - damaged - maint - lost
            if qty > usable:
                raise HTTPException(status_code=400, detail=f"Cannot mark {qty} units as lost. Only {usable} usable units in stock.")
            lost += qty
            movement_type = "Lost"
            notes = req.notes or f"Recorded {qty} lost units"
        elif action == "recover":
            if qty > lost:
                raise HTTPException(status_code=400, detail=f"Cannot recover {qty} units. Only {lost} units currently marked as lost.")
            lost -= qty
            movement_type = "Recovered"
            notes = req.notes or f"Recovered {qty} previously lost units"
        else:
            raise HTTPException(status_code=400, detail=f"Unknown stock action '{action}'. Valid: add, damage, maintenance, repair, lost, recover.")

        # Enforce collective constraint
        if damaged + maint + lost > total:
            raise HTTPException(status_code=400, detail="Damaged, maintenance and lost quantities cannot exceed total physical stock.")

        cursor.execute(
            """
            UPDATE equipment_items
            SET total_quantity = %s, damaged_quantity = %s,
                maintenance_quantity = %s, lost_quantity = %s
            WHERE item_id = %s
            """,
            (total, damaged, maint, lost, item_id)
        )

        cursor.execute(
            """
            INSERT INTO equipment_stock_movements (item_id, movement_type, quantity, user_id, notes)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (item_id, movement_type, qty, current_user.user_id, notes)
        )

        log_system_audit(
            cursor,
            entity_type="Equipment",
            entity_id=item_id,
            action=f"Stock_{action.title()}",
            changed_by=current_user.user_id,
            old_values={"total": eq["total_quantity"], "damaged": eq["damaged_quantity"], "maint": eq["maintenance_quantity"], "lost": eq["lost_quantity"]},
            new_values={"total": total, "damaged": damaged, "maint": maint, "lost": lost, "adjustment": qty},
            remarks=notes
        )

    return get_equipment(item_id, db=db)


@router.patch("/{item_id}/status", summary="Activate or deactivate equipment item (Admin only)")
def update_equipment_status(
    item_id: int,
    req: EquipmentStatusUpdate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    with transaction_scope() as (conn, cursor):
        cursor.execute("SELECT * FROM equipment_items WHERE item_id = %s FOR UPDATE", (item_id,))
        eq = cursor.fetchone()
        if not eq:
            raise HTTPException(status_code=404, detail="Equipment item not found.")

        cursor.execute("UPDATE equipment_items SET is_active = %s WHERE item_id = %s", (1 if req.is_active else 0, item_id))

        log_system_audit(
            cursor,
            entity_type="Equipment",
            entity_id=item_id,
            action="StatusChanged",
            changed_by=current_user.user_id,
            old_values={"is_active": bool(eq["is_active"])},
            new_values={"is_active": req.is_active},
            remarks=f"Equipment item '{eq['item_name']}' {'activated' if req.is_active else 'deactivated'} by Admin {current_user.name}"
        )

    return {"message": f"Equipment item '{eq['item_name']}' {'activated' if req.is_active else 'deactivated'} successfully."}


@router.post("/{item_id}/issue", summary="Issue equipment with quantity handover (Admin/Staff)")
def issue_equipment(
    item_id: int,
    req: EquipmentIssueQuantityRequest,
    current_user: UserContext = Depends(require_roles(Role.ADMIN, Role.STAFF)),
    db=Depends(get_db)
):
    with transaction_scope() as (conn, cursor):
        # 1. Lock equipment row
        cursor.execute("SELECT * FROM equipment_items WHERE item_id = %s FOR UPDATE", (item_id,))
        eq = cursor.fetchone()
        if not eq:
            raise HTTPException(status_code=404, detail="Equipment item not found.")
        if not eq["is_active"]:
            raise HTTPException(status_code=400, detail=f"'{eq['item_name']}' is deactivated and cannot be issued.")

        # 2. Lock booking
        cursor.execute("SELECT booking_id, status FROM bookings WHERE booking_id = %s", (req.booking_id,))
        b = cursor.fetchone()
        if not b:
            raise HTTPException(status_code=404, detail="Booking not found.")
        if b["status"] != "Approved":
            raise HTTPException(status_code=400, detail=f"Cannot issue equipment for a {b['status']} booking. Booking must be Approved.")

        # 3. Lock booking_equipment_items record
        cursor.execute(
            """
            SELECT * FROM booking_equipment_items
            WHERE booking_id = %s AND item_id = %s
            FOR UPDATE
            """,
            (req.booking_id, item_id)
        )
        bei = cursor.fetchone()
        if not bei:
            # On-demand equipment allocation at Gym desk counter
            cursor.execute(
                """
                INSERT INTO booking_equipment_items (booking_id, item_id, requested_quantity, approved_quantity, issued_quantity)
                VALUES (%s, %s, %s, %s, 0)
                """,
                (req.booking_id, item_id, req.quantity, req.quantity)
            )
            bei_id = cursor.lastrowid
            bei = {
                "booking_equipment_id": bei_id,
                "booking_id": req.booking_id,
                "item_id": item_id,
                "requested_quantity": req.quantity,
                "approved_quantity": req.quantity,
                "issued_quantity": 0,
                "returned_good_quantity": 0,
                "returned_damaged_quantity": 0,
                "lost_quantity": 0
            }

        limit_qty = bei["approved_quantity"] if bei["approved_quantity"] > 0 else bei["requested_quantity"]
        new_issued_total = bei["issued_quantity"] + req.quantity
        if new_issued_total > limit_qty:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot issue {req.quantity} units of '{eq['item_name']}'. "
                    f"Already issued: {bei['issued_quantity']}, Approved limit: {limit_qty}."
                )
            )

        # Check physical usable stock
        usable_stock = eq["total_quantity"] - eq["damaged_quantity"] - eq["maintenance_quantity"] - eq["lost_quantity"]
        if req.quantity > usable_stock:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot physically issue {req.quantity} units. Only {usable_stock} undamaged units in stock at the Gym."
            )

        # Update issued quantity
        cursor.execute(
            """
            UPDATE booking_equipment_items
            SET issued_quantity = %s
            WHERE booking_equipment_id = %s
            """,
            (new_issued_total, bei["booking_equipment_id"])
        )

        # Record movement
        cursor.execute(
            """
            INSERT INTO equipment_stock_movements (item_id, movement_type, quantity, booking_id, user_id, notes)
            VALUES (%s, 'Issued', %s, %s, %s, %s)
            """,
            (
                item_id,
                req.quantity,
                req.booking_id,
                current_user.user_id,
                req.notes or f"Handed over {req.quantity} {eq['unit']} for booking BK-{req.booking_id}"
            )
        )
        cursor.execute(
            "UPDATE equipment_items SET availability_status = 'Issued' WHERE item_id = %s",
            (item_id,)
        )

        log_system_audit(
            cursor,
            entity_type="Equipment",
            entity_id=item_id,
            action="Issued",
            changed_by=current_user.user_id,
            old_values={"issued_quantity": bei["issued_quantity"]},
            new_values={"issued_quantity": new_issued_total, "issued_now": req.quantity, "booking_id": req.booking_id},
            remarks=f"Issued {req.quantity} {eq['unit']} to booking BK-{req.booking_id} by {current_user.name}"
        )

    return {
        "message": f"Issued {req.quantity} {eq['unit']} of '{eq['item_name']}' for booking BK-{req.booking_id}.",
        "booking_id": req.booking_id,
        "item_id": item_id,
        "issued_now": req.quantity,
        "total_issued": new_issued_total,
        "approved_limit": limit_qty
    }


@router.post("/{item_id}/return", summary="Return equipment with condition check and stock update (Admin/Staff)")
def return_equipment(
    item_id: int,
    req: EquipmentReturnQuantityRequest,
    current_user: UserContext = Depends(require_roles(Role.ADMIN, Role.STAFF)),
    db=Depends(get_db)
):
    with transaction_scope() as (conn, cursor):
        cursor.execute("SELECT * FROM equipment_items WHERE item_id = %s FOR UPDATE", (item_id,))
        eq = cursor.fetchone()
        if not eq:
            raise HTTPException(status_code=404, detail="Equipment item not found.")

        booking_id = req.booking_id
        if not booking_id:
            cursor.execute(
                """
                SELECT booking_id FROM booking_equipment_items
                WHERE item_id = %s AND issued_quantity > (returned_good_quantity + returned_damaged_quantity + lost_quantity)
                ORDER BY booking_equipment_id DESC LIMIT 1
                """,
                (item_id,)
            )
            found_b = cursor.fetchone()
            if found_b:
                booking_id = found_b["booking_id"]
            else:
                raise HTTPException(status_code=400, detail="No active loan booking found for this equipment.")

        # Lock booking_equipment_items
        cursor.execute(
            """
            SELECT * FROM booking_equipment_items
            WHERE booking_id = %s AND item_id = %s
            FOR UPDATE
            """,
            (booking_id, item_id)
        )
        bei = cursor.fetchone()
        if not bei:
            raise HTTPException(
                status_code=400,
                detail=f"Equipment '{eq['item_name']}' is not associated with booking BK-{req.booking_id}."
            )

        ret_good = req.get_good()
        ret_damaged = req.get_damaged()
        ret_lost = req.lost_quantity or 0
        total_returning = ret_good + ret_damaged + ret_lost
        if total_returning <= 0:
            raise HTTPException(status_code=400, detail="Return quantities must sum to at least 1 unit.")

        already_accounted = (bei["returned_good_quantity"] or 0) + (bei["returned_damaged_quantity"] or 0) + (bei["lost_quantity"] or 0)
        outstanding = (bei["issued_quantity"] or 0) - already_accounted

        if total_returning > outstanding:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot return {total_returning} units. "
                    f"Only {outstanding} units are currently outstanding on loan for this booking "
                    f"(Issued: {bei['issued_quantity']}, Already returned: {already_accounted})."
                )
            )

        new_good = (bei["returned_good_quantity"] or 0) + ret_good
        new_damaged = (bei["returned_damaged_quantity"] or 0) + ret_damaged
        new_lost = (bei["lost_quantity"] or 0) + ret_lost

        cursor.execute(
            """
            UPDATE booking_equipment_items
            SET returned_good_quantity = %s,
                returned_damaged_quantity = %s,
                lost_quantity = %s
            WHERE booking_equipment_id = %s
            """,
            (new_good, new_damaged, new_lost, bei["booking_equipment_id"])
        )

        # Update equipment_items counters if damaged or lost
        eq_damaged = eq["damaged_quantity"] + ret_damaged
        eq_lost = eq["lost_quantity"] + ret_lost
        next_condition = "Damaged" if ret_damaged > 0 else "Good"
        next_availability = "Maintenance" if ret_damaged > 0 else "Available"
        cursor.execute(
            """
            UPDATE equipment_items
            SET damaged_quantity = %s,
                lost_quantity = %s,
                condition_status = %s,
                availability_status = %s
            WHERE item_id = %s
            """,
            (eq_damaged, eq_lost, next_condition, next_availability, item_id)
        )

        # Record stock movements
        if ret_good > 0:
            cursor.execute(
                """
                INSERT INTO equipment_stock_movements (item_id, movement_type, quantity, booking_id, user_id, notes)
                VALUES (%s, 'Returned Good', %s, %s, %s, %s)
                """,
                (item_id, ret_good, booking_id, current_user.user_id, req.notes or req.remarks or "Returned in good condition")
            )

        if ret_damaged > 0:
            cursor.execute(
                """
                INSERT INTO equipment_stock_movements (item_id, movement_type, quantity, booking_id, user_id, notes)
                VALUES (%s, 'Returned Damaged', %s, %s, %s, %s)
                """,
                (item_id, ret_damaged, booking_id, current_user.user_id, req.notes or req.remarks or "Returned damaged")
            )
            # Create maintenance record for inspection
            cursor.execute(
                """
                INSERT INTO maintenance_records (item_id, reported_by, issue_description, status, remarks)
                VALUES (%s, %s, %s, 'Open', %s)
                """,
                (
                    item_id,
                    current_user.user_id,
                    f"{ret_damaged} {eq['unit']}(s) returned DAMAGED from booking BK-{booking_id}. {req.notes or req.remarks or ''}",
                    req.notes or req.remarks or "Requires technician assessment"
                )
            )

        if ret_lost > 0:
            cursor.execute(
                """
                INSERT INTO equipment_stock_movements (item_id, movement_type, quantity, booking_id, user_id, notes)
                VALUES (%s, 'Lost', %s, %s, %s, %s)
                """,
                (item_id, ret_lost, booking_id, current_user.user_id, req.notes or req.remarks or "Recorded as lost / not returned")
            )

        log_system_audit(
            cursor,
            entity_type="Equipment",
            entity_id=item_id,
            action="Returned",
            changed_by=current_user.user_id,
            old_values={"outstanding": outstanding},
            new_values={
                "returned_good": ret_good,
                "returned_damaged": ret_damaged,
                "lost": ret_lost,
                "booking_id": booking_id
            },
            remarks=f"Processed return of {total_returning} {eq['unit']} for booking BK-{booking_id}"
        )

    return {
        "message": f"Successfully processed return of {total_returning} units of '{eq['item_name']}'.",
        "condition_status": "Damaged" if ret_damaged > 0 else "Good",
        "availability_status": "Maintenance" if ret_damaged > 0 else "Available",
        "returned_good": ret_good,
        "returned_damaged": ret_damaged,
        "lost": ret_lost,
        "returned_good_quantity": new_good,
        "returned_damaged_quantity": new_damaged,
        "lost_quantity": new_lost,
        "remaining_outstanding": outstanding - total_returning
    }


@router.get("/{item_id}/movements", response_model=List[EquipmentStockMovementResponse], summary="Get equipment movement audit trail (Admin/Staff)")
def get_equipment_movements(
    item_id: int,
    current_user: UserContext = Depends(require_roles(Role.ADMIN, Role.STAFF)),
    db=Depends(get_db)
):
    query = """
        SELECT m.movement_id, m.item_id, m.movement_type, m.quantity,
               m.booking_id, m.user_id, m.created_at, m.notes,
               e.item_name, u.name as user_name
        FROM equipment_stock_movements m
        JOIN equipment_items e ON m.item_id = e.item_id
        LEFT JOIN users u ON m.user_id = u.user_id
        WHERE m.item_id = %s
        ORDER BY m.created_at DESC, m.movement_id DESC
        LIMIT 200
    """
    db.execute(query, (item_id,))
    rows = db.fetchall()
    return [EquipmentStockMovementResponse.model_validate(r) for r in rows]
