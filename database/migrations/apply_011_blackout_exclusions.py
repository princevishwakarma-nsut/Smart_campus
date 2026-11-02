import os
import sys

import mysql.connector
from dotenv import load_dotenv

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
backend_dir = os.path.join(root_dir, "backend")
load_dotenv(os.path.join(backend_dir, ".env"))
sys.path.insert(0, backend_dir)

from app.core.config import settings


def apply_migration_011(target_db=None):
    database_name = target_db or settings.DB_NAME
    print(f"Applying Migration 011 to database: {database_name}...")
    conn = mysql.connector.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=database_name
    )
    cursor = conn.cursor()
    cursor.execute("SHOW COLUMNS FROM resource_blackout_periods LIKE 'excluded_resource_ids'")
    if cursor.fetchone():
        print("Blackout resource exclusion column already exists; no changes made.")
    else:
        cursor.execute(
            "ALTER TABLE resource_blackout_periods ADD COLUMN excluded_resource_ids JSON NULL AFTER category_ids"
        )
        conn.commit()
        print("Migration 011 applied successfully.")
    cursor.close()
    conn.close()


if __name__ == "__main__":
    apply_migration_011()
