import os
import sys

import mysql.connector
from dotenv import load_dotenv

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
backend_dir = os.path.join(root_dir, "backend")
load_dotenv(os.path.join(backend_dir, ".env"))
sys.path.insert(0, backend_dir)

from app.core.config import settings


def apply_migration_008(target_db=None):
    database_name = target_db or settings.DB_NAME
    print(f"Applying Migration 008 to database: {database_name}...")
    conn = mysql.connector.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=database_name
    )
    cursor = conn.cursor()
    migration_path = os.path.join(os.path.dirname(__file__), "008_runtime_booking_settings.sql")
    with open(migration_path, "r", encoding="utf-8") as migration_file:
        statements = [statement.strip() for statement in migration_file.read().split(";") if statement.strip()]
    for statement in statements:
        cursor.execute(statement)
    conn.commit()
    cursor.close()
    conn.close()
    print("Migration 008 applied successfully.")


if __name__ == "__main__":
    apply_migration_008()
