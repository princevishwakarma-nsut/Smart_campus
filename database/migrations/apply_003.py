import os
import sys
import mysql.connector

from dotenv import load_dotenv

# Set up paths for importing settings
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
backend_dir = os.path.join(root_dir, "backend")
env_path = os.path.join(backend_dir, ".env")
load_dotenv(env_path)

sys.path.insert(0, backend_dir)

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


def apply_migration_003(target_db=None):
    database_name = target_db or db_name
    print(f"Applying Migration 003 to database: {database_name}...")
    conn = mysql.connector.connect(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_password,
        database=database_name
    )
    cursor = conn.cursor()

    # 1. Create faculty_requests table
    cursor.execute("SHOW TABLES LIKE 'faculty_requests'")
    if not cursor.fetchone():
        print("Creating table faculty_requests...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS faculty_requests (
                request_id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(150) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                department_id INT NULL,
                phone_no VARCHAR(20) NULL,
                employee_id VARCHAR(50) NOT NULL,
                designation VARCHAR(100) NULL,
                status ENUM('Pending', 'Approved', 'Rejected') NOT NULL DEFAULT 'Pending',
                reviewed_by INT NULL,
                reviewed_at TIMESTAMP NULL,
                rejection_reason VARCHAR(255) NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_faculty_req_email (email),
                INDEX idx_faculty_req_status (status),
                CONSTRAINT fk_faculty_req_dept FOREIGN KEY (department_id) REFERENCES departments(department_id) ON DELETE SET NULL,
                CONSTRAINT fk_faculty_req_reviewer FOREIGN KEY (reviewed_by) REFERENCES users(user_id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        conn.commit()
        print("Table faculty_requests created successfully.")
    else:
        print("Table faculty_requests already exists.")

    # 2. Add columns to societies table
    cursor.execute("SHOW COLUMNS FROM societies LIKE 'status'")
    if not cursor.fetchone():
        print("Adding approval columns to societies table...")
        cursor.execute("""
            ALTER TABLE societies
            ADD COLUMN status ENUM('Pending', 'Approved', 'Rejected') NOT NULL DEFAULT 'Approved',
            ADD COLUMN rejection_reason VARCHAR(255) NULL,
            ADD COLUMN reviewed_by INT NULL,
            ADD COLUMN reviewed_at TIMESTAMP NULL,
            ADD CONSTRAINT fk_societies_reviewer
              FOREIGN KEY (reviewed_by)
              REFERENCES users(user_id)
              ON UPDATE CASCADE
              ON DELETE SET NULL
        """)
        conn.commit()
        print("Added columns status, rejection_reason, reviewed_by, reviewed_at to societies table.")
    else:
        print("Column 'status' already exists in societies.")

    cursor.close()
    conn.close()
    print("Migration 003 completed successfully.")


if __name__ == "__main__":
    apply_migration_003()
