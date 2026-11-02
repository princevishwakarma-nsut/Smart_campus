import os
import sys

import mysql.connector
from dotenv import load_dotenv

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
backend_dir = os.path.join(root_dir, "backend")
load_dotenv(os.path.join(backend_dir, ".env"))
sys.path.insert(0, backend_dir)

from app.core.config import settings


def apply_migration_010(target_db=None):
    database_name = target_db or settings.DB_NAME
    print(f"Applying Migration 010 to database: {database_name}...")
    conn = mysql.connector.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=database_name
    )
    cursor = conn.cursor()
    cursor.execute("SHOW COLUMNS FROM resource_blackout_periods LIKE 'blackout_group_id'")
    if cursor.fetchone():
        print("Advanced blackout columns already exist; no changes made.")
    else:
        migration_path = os.path.join(os.path.dirname(__file__), "010_advanced_blackout_management.sql")
        with open(migration_path, "r", encoding="utf-8") as migration_file:
            for statement in migration_file.read().split(";"):
                if statement.strip():
                    cursor.execute(statement)
        conn.commit()
        print("Migration 010 applied successfully.")
    cursor.close()
    conn.close()


if __name__ == "__main__":
    apply_migration_010()
