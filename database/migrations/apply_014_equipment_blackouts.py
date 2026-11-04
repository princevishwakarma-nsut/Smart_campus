import os

import mysql.connector
from dotenv import load_dotenv

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
backend_dir = os.path.join(root_dir, "backend")
load_dotenv(os.path.join(backend_dir, ".env"))

import sys
sys.path.insert(0, backend_dir)

from app.core.config import settings


def apply_migration_014(target_db=None):
    database_name = target_db or settings.DB_NAME
    print(f"Applying Migration 014 to database: {database_name}...")
    conn = mysql.connector.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=database_name,
    )
    cursor = conn.cursor()
    try:
        cursor.execute("SHOW TABLES LIKE 'equipment_blackout_periods'")
        if cursor.fetchone():
            print("Equipment blackout table already exists; no changes made.")
            return
        migration_path = os.path.join(
            os.path.dirname(__file__), "014_equipment_blackouts.sql"
        )
        with open(migration_path, "r", encoding="utf-8") as migration_file:
            cursor.execute(migration_file.read())
        conn.commit()
        print("Migration 014 applied successfully.")
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    apply_migration_014()
