import sys
from pathlib import Path

import mysql.connector
from mysql.connector import Error

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

from app.core.config import settings
from app.database.connection import build_mysql_connection_config

EXPECTED_TABLES = [
    "booking_approvals",
    "booking_audit",
    "booking_equipment_items",
    "booking_participants",
    "booking_resources",
    "bookings",
    "categories",
    "departments",
    "equipment_blackout_periods",
    "equipment_items",
    "equipment_stock_movements",
    "faculty_requests",
    "maintenance_records",
    "notifications",
    "resource_blackout_periods",
    "resource_features",
    "resource_operating_hour_exceptions",
    "resource_operating_hours",
    "resource_timetable",
    "resources",
    "societies",
    "society_members",
    "system_audit",
    "system_settings",
    "timetable_faculty_assignments",
    "users",
    "checkins",
]

IMPORTANT_TABLES = [
    "users",
    "departments",
    "resources",
    "bookings",
    "booking_resources",
    "booking_approvals",
    "equipment_items",
    "equipment_stock_movements",
    "resource_timetable",
    "notifications",
    "societies",
    "system_audit",
]


def main() -> int:
    if not settings.DB_PASSWORD or settings.DB_PASSWORD in {"ENTER_AIVEN_PASSWORD_HERE", "your_mysql_password_here"}:
        print("DB_PASSWORD is missing or still set to a placeholder value. Update backend/.env first.", file=sys.stderr)
        return 1

    conn = None
    try:
        conn = mysql.connector.connect(**build_mysql_connection_config())
        print(f"Selected database: {settings.DB_NAME}")

        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT VERSION() AS version")
        version = cursor.fetchone()["version"]
        print(f"MySQL server version: {version}")

        cursor.execute("SHOW STATUS LIKE 'Ssl_cipher'")
        cipher_row = cursor.fetchone()
        cipher = cipher_row["Value"] if cipher_row else "unknown"
        print(f"TLS cipher: {cipher}")

        cursor.execute("SELECT 1 AS alive")
        alive = cursor.fetchone()["alive"]
        print(f"SELECT 1 result: {alive}")

        cursor.execute("SHOW TABLES")
        tables = [row[f"Tables_in_{settings.DB_NAME}"] for row in cursor.fetchall()]
        print(f"Discovered tables: {len(tables)}")

        missing = [table for table in EXPECTED_TABLES if table not in tables]
        if missing:
            raise RuntimeError(f"Missing expected tables: {', '.join(missing)}")

        print("Verified expected tables exist.")

        for table in IMPORTANT_TABLES:
            cursor.execute(f"SELECT COUNT(*) AS total FROM `{table}`")
            total = cursor.fetchone()["total"]
            print(f"{table}: {total} rows")

        cursor.close()
        conn.close()
        return 0
    except FileNotFoundError as exc:
        print(f"Invalid CA certificate path: {exc}", file=sys.stderr)
        return 1
    except Error as exc:
        print(f"MySQL connection failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Aiven database validation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None and conn.is_connected():
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
