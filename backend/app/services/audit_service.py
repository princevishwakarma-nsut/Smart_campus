import json
from typing import Any, Dict, Optional


def sanitize_audit_dict(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Remove any passwords, hashes, tokens, or sensitive credentials before writing to audit JSON."""
    if not data or not isinstance(data, dict):
        return data

    sanitized = {}
    forbidden_keys = {"password", "password_hash", "pass", "token", "access_token", "secret", "secret_key"}
    for k, v in data.items():
        if k.lower() in forbidden_keys:
            sanitized[k] = "[REDACTED]"
        else:
            sanitized[k] = v
    return sanitized


def log_booking_audit(
    cursor,
    booking_id: int,
    changed_by: Optional[int],
    action: str,
    old_values: Optional[dict] = None,
    new_values: Optional[dict] = None,
    remarks: Optional[str] = None
) -> int:
    """Append-only audit logging dedicated to booking lifecycles."""
    safe_old = sanitize_audit_dict(old_values)
    safe_new = sanitize_audit_dict(new_values)

    cursor.execute(
        """
        INSERT INTO booking_audit (booking_id, changed_by, action, old_values, new_values, remarks)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            booking_id,
            changed_by,
            action,
            json.dumps(safe_old) if safe_old else None,
            json.dumps(safe_new) if safe_new else None,
            remarks
        )
    )
    return cursor.lastrowid


def log_system_audit(
    cursor,
    entity_type: str,
    entity_id: int,
    action: str,
    changed_by: Optional[int],
    old_values: Optional[dict] = None,
    new_values: Optional[dict] = None,
    remarks: Optional[str] = None
) -> int:
    """Append-only generic system audit for non-booking resources, users, maintenance, equipment, societies."""
    safe_old = sanitize_audit_dict(old_values)
    safe_new = sanitize_audit_dict(new_values)

    cursor.execute(
        """
        INSERT INTO system_audit (entity_type, entity_id, action, changed_by, old_values, new_values, remarks)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            entity_type,
            entity_id,
            action,
            changed_by,
            json.dumps(safe_old) if safe_old else None,
            json.dumps(safe_new) if safe_new else None,
            remarks
        )
    )
    return cursor.lastrowid
