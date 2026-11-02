"""Migration 006 Applicator: Adds token_version to users table in MySQL smart_campus.
"""
import sys
import os

BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend")
sys.path.insert(0, BACKEND_DIR)

from app.database.connection import get_connection_pool


def apply_migration_006():
    pool = get_connection_pool()
    conn = pool.get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Check if token_version column already exists in users
        cursor.execute("""
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'users'
              AND COLUMN_NAME = 'token_version'
        """)
        row = cursor.fetchone()
        if not row:
            print("Adding token_version column to users table...")
            cursor.execute("""
                ALTER TABLE users
                ADD COLUMN token_version INT NOT NULL DEFAULT 1 AFTER is_active
            """)
            conn.commit()
            print("Successfully added token_version column to users table.")
        else:
            print("Column token_version already exists in users table.")
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    apply_migration_006()
