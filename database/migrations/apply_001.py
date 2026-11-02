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

# 1. Add maintenance_id column to resource_blackout_periods
cursor.execute("SHOW COLUMNS FROM resource_blackout_periods LIKE 'maintenance_id'")
if not cursor.fetchone():
    print("Applying ALTER TABLE resource_blackout_periods...")
    cursor.execute("""
        ALTER TABLE resource_blackout_periods
        ADD COLUMN maintenance_id INT NULL AFTER resource_id,
        ADD CONSTRAINT fk_blackout_maintenance
          FOREIGN KEY (maintenance_id)
          REFERENCES maintenance_records(maintenance_id)
          ON UPDATE CASCADE
          ON DELETE RESTRICT
    """)
    conn.commit()
    print("ALTER TABLE successful!")
else:
    print("Column maintenance_id already exists in resource_blackout_periods.")

# 2. Create system_audit table
cursor.execute("SHOW TABLES LIKE 'system_audit'")
if not cursor.fetchone():
    print("Creating system_audit table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_audit (
          audit_id INT AUTO_INCREMENT PRIMARY KEY,
          entity_type VARCHAR(50) NOT NULL,
          entity_id INT NOT NULL,
          action VARCHAR(100) NOT NULL,
          changed_by INT NULL,
          old_values JSON NULL,
          new_values JSON NULL,
          remarks TEXT,
          created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          INDEX idx_system_audit_entity (entity_type, entity_id),
          INDEX idx_system_audit_changed_by (changed_by),
          INDEX idx_system_audit_created_at (created_at),
          CONSTRAINT fk_system_audit_user
            FOREIGN KEY (changed_by)
            REFERENCES users(user_id)
            ON UPDATE CASCADE
            ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    conn.commit()
    print("CREATE TABLE system_audit successful!")
else:
    print("Table system_audit already exists.")

conn.close()
print("Migration 001 verification finished.")
