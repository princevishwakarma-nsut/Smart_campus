from typing import Dict, List, Sequence

from fastapi import HTTPException, status

from app.schemas.operating_hours import WEEKDAYS


WEEKDAY_INDEX = {day: index for index, day in enumerate(WEEKDAYS)}


def resolve_operating_resources(
    cursor,
    resource_ids: Sequence[int],
    category_ids: Sequence[int],
    all_resources: bool,
    lock: bool = False,
) -> List[Dict]:
    resource_ids = sorted(set(resource_ids))
    category_ids = sorted(set(category_ids))
    if not (resource_ids or category_ids or all_resources):
        raise HTTPException(status_code=422, detail="Select resources, categories, or all resources.")

    if category_ids:
        cursor.execute(
            f"SELECT category_id FROM categories WHERE category_id IN ({','.join(['%s'] * len(category_ids))})",
            tuple(category_ids),
        )
        found_categories = {row["category_id"] for row in cursor.fetchall()}
        missing_categories = sorted(set(category_ids) - found_categories)
        if missing_categories:
            raise HTTPException(status_code=404, detail=f"Categories not found: {missing_categories}.")

    conditions = []
    params = []
    if all_resources:
        conditions.append("1 = 1")
    else:
        if resource_ids:
            conditions.append(f"r.resource_id IN ({','.join(['%s'] * len(resource_ids))})")
            params.extend(resource_ids)
        if category_ids:
            conditions.append(f"r.category_id IN ({','.join(['%s'] * len(category_ids))})")
            params.extend(category_ids)

    query = f"""
        SELECT r.resource_id, r.resource_name, r.category_id, c.category_name
        FROM resources r
        JOIN categories c ON c.category_id = r.category_id
        WHERE ({' OR '.join(conditions)})
        ORDER BY r.resource_id
        {"FOR UPDATE" if lock else ""}
    """
    cursor.execute(query, tuple(params))
    resources = cursor.fetchall()
    found_ids = {row["resource_id"] for row in resources}
    missing_ids = sorted(set(resource_ids) - found_ids)
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"Resources not found: {missing_ids}.")
    if not resources:
        raise HTTPException(status_code=422, detail="The selected categories contain no resources.")
    return resources


def save_weekly_hours(cursor, resources: Sequence[Dict], payload, actor_id: int) -> int:
    schedule_by_day = {}
    for day in payload.weekdays:
        schedule_by_day[WEEKDAY_INDEX[day]] = (False, payload.open_time, payload.close_time)
    for day in payload.closed_days:
        schedule_by_day[WEEKDAY_INDEX[day]] = (True, None, None)

    for resource in resources:
        resource_id = resource["resource_id"]
        for weekday in range(len(WEEKDAY_INDEX)):
            is_closed, opens, closes = schedule_by_day.get(weekday, (True, None, None))
            cursor.execute(
                """
                INSERT INTO resource_operating_hours
                    (resource_id, weekday, is_closed, open_time, close_time, is_active, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    is_closed = VALUES(is_closed),
                    open_time = VALUES(open_time),
                    close_time = VALUES(close_time),
                    is_active = VALUES(is_active),
                    updated_by = VALUES(updated_by)
                """,
                (resource_id, weekday, is_closed, opens, closes, payload.is_active, actor_id),
            )
    return len(resources)


def validate_exception_ranges(cursor, resources: Sequence[Dict], start_date, end_date) -> None:
    resource_ids = [resource["resource_id"] for resource in resources]
    placeholders = ",".join(["%s"] * len(resource_ids))
    cursor.execute(
        f"""
        SELECT e.resource_id, r.resource_name, e.start_date, e.end_date, e.reason
        FROM resource_operating_hour_exceptions e
        JOIN resources r ON r.resource_id = e.resource_id
        WHERE e.resource_id IN ({placeholders})
          AND e.status = 'Active'
          AND e.start_date <= %s
          AND e.end_date >= %s
        ORDER BY e.resource_id, e.start_date
        """,
        (*resource_ids, end_date, start_date),
    )
    conflicts = cursor.fetchall()
    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "An active operating-hours exception already overlaps the selected dates.",
                "conflicts": [
                    {
                        "resource_id": row["resource_id"],
                        "resource_name": row["resource_name"],
                        "start_date": row["start_date"].isoformat(),
                        "end_date": row["end_date"].isoformat(),
                        "reason": row["reason"],
                    }
                    for row in conflicts
                ],
            },
        )
