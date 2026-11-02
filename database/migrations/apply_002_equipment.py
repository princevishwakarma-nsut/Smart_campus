import os
import sys
import mysql.connector

# Load settings from app.core.config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

try:
    from app.core.config import settings
    db_host = settings.DB_HOST
    db_port = settings.DB_PORT
    db_user = settings.DB_USER
    db_password = settings.DB_PASSWORD
    db_name = settings.DB_NAME
except Exception:
    db_host = os.getenv("DB_HOST", "127.0.0.1")
    db_port = int(os.getenv("DB_PORT", 3306))
    db_user = os.getenv("DB_USER", "root")
    db_password = os.getenv("DB_PASSWORD", "")
    db_name = os.getenv("DB_NAME", "smart_campus")

conn = mysql.connector.connect(
    host=db_host,
    port=db_port,
    user=db_user,
    password=db_password,
    database=db_name
)
cursor = conn.cursor()

# Modify issued_at to be NULLABLE so items can be reserved during booking without marking as issued
cursor.execute("ALTER TABLE booking_equipment_items MODIFY COLUMN issued_at DATETIME NULL DEFAULT NULL")
conn.commit()
print("ALTER TABLE booking_equipment_items: issued_at is now NULLABLE!")

conn.close()
