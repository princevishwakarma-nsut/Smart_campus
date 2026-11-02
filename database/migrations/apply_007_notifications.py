import os
import sys
import mysql.connector
from dotenv import load_dotenv

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
backend_dir = os.path.join(root_dir, "backend")
load_dotenv(os.path.join(backend_dir, ".env"))
sys.path.insert(0, backend_dir)

from app.core.config import settings


def apply_migration_007(target_db=None):
    database_name = target_db or settings.DB_NAME
    print(f"Applying Migration 007 to database: {database_name}...")
    conn = mysql.connector.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=database_name
    )
    cursor = conn.cursor()

    cursor.execute("SHOW COLUMNS FROM notifications LIKE 'audience'")
    if not cursor.fetchone():
        cursor.execute("""
            ALTER TABLE notifications
            ADD COLUMN audience ENUM('User', 'Admin') NOT NULL DEFAULT 'User' AFTER user_id
        """)

    cursor.execute("""
        UPDATE notifications n
        JOIN users u ON u.user_id = n.user_id
        SET n.audience = 'Admin'
        WHERE u.role = 'Admin'
          AND n.message LIKE 'New booking request BK-% requires your approval.%'
    """)

    cursor.execute("SHOW INDEX FROM notifications WHERE Key_name = 'idx_notifications_user_audience_read'")
    if not cursor.fetchone():
        cursor.execute("""
            CREATE INDEX idx_notifications_user_audience_read
            ON notifications (user_id, audience, is_read)
        """)

    conn.commit()
    cursor.close()
    conn.close()
    print("Migration 007 applied successfully.")


if __name__ == "__main__":
    apply_migration_007()
