"""
Migration 004: Add user_id to faculty_requests and align collation with users table.
Preserves all existing data, passwords, audit records, and constraints.
"""
import sys
import os

# Add backend directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
from app.database.connection import get_db_connection


def run_migration():
    print("Connecting to MySQL database...")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1. Align collation of faculty_requests to utf8mb4_0900_ai_ci
        cursor.execute("ALTER TABLE faculty_requests CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
        print("Aligned faculty_requests character set and collation.")

        # 2. Add user_id column if not exists
        cursor.execute("SHOW COLUMNS FROM faculty_requests LIKE 'user_id'")
        if not cursor.fetchone():
            cursor.execute("""
                ALTER TABLE faculty_requests
                ADD COLUMN user_id INT NULL AFTER request_id,
                ADD CONSTRAINT fk_faculty_req_user
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ON DELETE SET NULL
                    ON UPDATE CASCADE
            """)
            print("Added user_id column and foreign key constraint.")
        else:
            print("user_id column already exists.")

        # 3. Link existing requests to users
        cursor.execute("""
            UPDATE faculty_requests fr
            JOIN users u ON fr.email = u.email
            SET fr.user_id = u.user_id
            WHERE fr.user_id IS NULL
        """)
        print(f"Linked {cursor.rowcount} existing faculty_requests to users table.")

        conn.commit()
        print("Migration 004 completed successfully.")
    except Exception as e:
        conn.rollback()
        print(f"Migration 004 failed: {e}")
        raise e
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    run_migration()
