import os
import sys

import mysql.connector
from dotenv import load_dotenv

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
backend_dir = os.path.join(root_dir, "backend")
load_dotenv(os.path.join(backend_dir, ".env"))
sys.path.insert(0, backend_dir)

from app.core.config import settings


def apply_migration_012(target_db=None):
    database_name = target_db or settings.DB_NAME
    print(f"Applying Migration 012 to database: {database_name}...")
    conn = mysql.connector.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=database_name,
    )
    cursor = conn.cursor()
    migration_path = os.path.join(os.path.dirname(__file__), "012_operating_hours_and_maintenance.sql")
    with open(migration_path, "r", encoding="utf-8") as migration_file:
        statements = [statement.strip() for statement in migration_file.read().split(";") if statement.strip()]

    try:
        for statement in statements:
            if statement.upper().startswith("ALTER TABLE MAINTENANCE_RECORDS"):
                cursor.execute("SHOW COLUMNS FROM maintenance_records LIKE 'maintenance_type'")
                if cursor.fetchone():
                    continue
            cursor.execute(statement)
        conn.commit()
        print("Migration 012 applied successfully.")
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    apply_migration_012()
