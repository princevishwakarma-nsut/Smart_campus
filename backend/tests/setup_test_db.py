import re
import os
import sys
import mysql.connector

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.config import settings
from app.core.security import get_password_hash


def setup_isolated_test_database():
    """
    Sets up an isolated 'smart_campus_test' database.
    Zero interaction with or modification of the live 'smart_campus' database.
    """
    conn = mysql.connector.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD
    )
    cursor = conn.cursor()

    # Recreate test database cleanly
    cursor.execute("DROP DATABASE IF EXISTS smart_campus_test")
    cursor.execute("CREATE DATABASE smart_campus_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    cursor.execute("USE smart_campus_test")

    # Read base schema
    schema_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "database", "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        sql_content = f.read()

    # Replace database name references
    sql_content = sql_content.replace("smart_campus", "smart_campus_test")

    # Split into statements
    statements = sql_content.split(";")
    cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
    for stmt in statements:
        s = stmt.strip()
        if s and not s.startswith("--") and not s.upper().startswith("CREATE DATABASE") and not s.upper().startswith("USE"):
            try:
                cursor.execute(s)
            except Exception as e:
                # ignore comments or drop errors
                pass

    # Apply Migration 001 (maintenance_id & system_audit)
    cursor.execute("SHOW COLUMNS FROM resource_blackout_periods LIKE 'maintenance_id'")
    if not cursor.fetchone():
        cursor.execute("""
            ALTER TABLE resource_blackout_periods
            ADD COLUMN maintenance_id INT NULL AFTER resource_id,
            ADD CONSTRAINT fk_test_blackout_maint
              FOREIGN KEY (maintenance_id)
              REFERENCES maintenance_records(maintenance_id)
              ON UPDATE CASCADE
              ON DELETE RESTRICT
        """)

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
          CONSTRAINT fk_test_system_audit_user
            FOREIGN KEY (changed_by)
            REFERENCES users(user_id)
            ON UPDATE CASCADE
            ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)

    # Apply Migration 002 (issued_at nullable)
    cursor.execute("ALTER TABLE booking_equipment_items MODIFY COLUMN issued_at DATETIME NULL DEFAULT NULL")

    # Apply Migration 003, 004 & 005
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS faculty_requests (
            request_id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NULL,
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
            CONSTRAINT fk_test_faculty_req_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL,
            CONSTRAINT fk_test_faculty_req_dept FOREIGN KEY (department_id) REFERENCES departments(department_id) ON DELETE SET NULL,
            CONSTRAINT fk_test_faculty_req_reviewer FOREIGN KEY (reviewed_by) REFERENCES users(user_id) ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS timetable_faculty_assignments (
            assignment_id INT AUTO_INCREMENT PRIMARY KEY,
            timetable_id INT NOT NULL,
            faculty_user_id INT NOT NULL,
            assigned_by INT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_timetable_faculty (timetable_id, faculty_user_id),
            KEY idx_tfa_faculty (faculty_user_id),
            KEY idx_tfa_timetable (timetable_id),
            CONSTRAINT fk_test_tfa_timetable FOREIGN KEY (timetable_id) REFERENCES resource_timetable(timetable_id) ON DELETE CASCADE,
            CONSTRAINT fk_test_tfa_faculty FOREIGN KEY (faculty_user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            CONSTRAINT fk_test_tfa_assigned_by FOREIGN KEY (assigned_by) REFERENCES users(user_id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """)

    # Seed Sports Facility category and resources in test DB
    cursor.execute("SELECT category_id FROM categories WHERE category_name = 'Sports Facility'")
    row_cat = cursor.fetchone()
    if not row_cat:
        cursor.execute("INSERT INTO categories (category_name, description) VALUES ('Sports Facility', 'Indoor and outdoor athletic facilities.')")
        sports_cat_id = cursor.lastrowid
    else:
        sports_cat_id = row_cat[0]

    sports_facilities = [
        ("Sports Complex", "SPT-CMPLX", "Campus Sports Area", 500, "Multi-purpose sports complex"),
        ("Football Ground", "SPT-FTB-GRD", "Main Sports Field", 200, "Football ground"),
        ("Basketball Court", "SPT-BSK-CRT", "Sports Complex Outdoor", 50, "Basketball court"),
        ("Volleyball Court", "SPT-VLB-CRT", "Sports Complex Outdoor", 40, "Volleyball court"),
        ("Badminton Court", "SPT-BAD-CRT", "Indoor Sports Complex", 30, "Badminton court"),
        ("Tennis Court", "SPT-TNS-CRT", "Sports Complex Outdoor", 30, "Tennis court")
    ]
    for name, code, loc, cap, desc in sports_facilities:
        cursor.execute("SELECT resource_id FROM resources WHERE resource_code = %s", (code,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO resources (category_id, resource_name, resource_code, location, capacity, status, description) VALUES (%s, %s, %s, %s, %s, 'Available', %s)",
                           (sports_cat_id, name, code, loc, cap, desc))

    cursor.execute("SHOW COLUMNS FROM societies LIKE 'status'")
    if not cursor.fetchone():
        cursor.execute("""
            ALTER TABLE societies
            ADD COLUMN status ENUM('Pending', 'Approved', 'Rejected') NOT NULL DEFAULT 'Approved',
            ADD COLUMN rejection_reason VARCHAR(255) NULL,
            ADD COLUMN reviewed_by INT NULL,
            ADD COLUMN reviewed_at TIMESTAMP NULL,
            ADD CONSTRAINT fk_test_soc_rev
              FOREIGN KEY (reviewed_by)
              REFERENCES users(user_id)
              ON UPDATE CASCADE
              ON DELETE SET NULL
        """)

    # Apply Migration 004 (Quantity-based equipment inventory)
    cursor.execute("SHOW COLUMNS FROM bookings LIKE 'start_time'")
    if not cursor.fetchone():
        cursor.execute("""
            ALTER TABLE bookings
            ADD COLUMN start_time DATETIME NULL,
            ADD COLUMN end_time DATETIME NULL
        """)

    cursor.execute("SHOW COLUMNS FROM equipment_items LIKE 'item_code'")
    if not cursor.fetchone():
        cursor.execute("""
            ALTER TABLE equipment_items
            ADD COLUMN item_code VARCHAR(50) NULL AFTER item_id,
            ADD COLUMN category ENUM('Sports', 'Electronics', 'Audio/Visual', 'IT', 'Accessories', 'Other') NOT NULL DEFAULT 'Other' AFTER item_name,
            ADD COLUMN unit VARCHAR(50) NOT NULL DEFAULT 'Piece' AFTER description,
            ADD COLUMN total_quantity INT NOT NULL DEFAULT 1 AFTER unit,
            ADD COLUMN damaged_quantity INT NOT NULL DEFAULT 0 AFTER total_quantity,
            ADD COLUMN maintenance_quantity INT NOT NULL DEFAULT 0 AFTER damaged_quantity,
            ADD COLUMN lost_quantity INT NOT NULL DEFAULT 0 AFTER maintenance_quantity,
            ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 1 AFTER purchase_date,
            ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP AFTER created_at
        """)

    cursor.execute("""
        UPDATE equipment_items
        SET item_code = CONCAT('EQ-', LPAD(item_id, 3, '0'))
        WHERE item_code IS NULL OR TRIM(item_code) = ''
    """)
    cursor.execute("ALTER TABLE equipment_items MODIFY COLUMN item_code VARCHAR(50) NOT NULL")
    cursor.execute("DROP TRIGGER IF EXISTS trg_equipment_item_code_default_insert")
    cursor.execute("""
        CREATE TRIGGER trg_equipment_item_code_default_insert
        BEFORE INSERT ON equipment_items
        FOR EACH ROW
        BEGIN
            IF NEW.item_code IS NULL OR TRIM(NEW.item_code) = '' THEN
                SET NEW.item_code = CONCAT('EQ-', UPPER(SUBSTRING(REPLACE(UUID(), '-', ''), 1, 8)));
            END IF;
        END
    """)
    cursor.execute("DROP TRIGGER IF EXISTS trg_equipment_item_code_default_update")
    cursor.execute("""
        CREATE TRIGGER trg_equipment_item_code_default_update
        BEFORE UPDATE ON equipment_items
        FOR EACH ROW
        BEGIN
            IF NEW.item_code IS NULL OR TRIM(NEW.item_code) = '' THEN
                SET NEW.item_code = CONCAT('EQ-', UPPER(SUBSTRING(REPLACE(UUID(), '-', ''), 1, 8)));
            END IF;
        END
    """)

    cursor.execute("SHOW COLUMNS FROM booking_equipment_items LIKE 'requested_quantity'")
    if not cursor.fetchone():
        cursor.execute("""
            ALTER TABLE booking_equipment_items
            ADD COLUMN requested_quantity INT NOT NULL DEFAULT 1 AFTER item_id,
            ADD COLUMN approved_quantity INT NOT NULL DEFAULT 0 AFTER requested_quantity,
            ADD COLUMN issued_quantity INT NOT NULL DEFAULT 0 AFTER approved_quantity,
            ADD COLUMN returned_good_quantity INT NOT NULL DEFAULT 0 AFTER issued_quantity,
            ADD COLUMN returned_damaged_quantity INT NOT NULL DEFAULT 0 AFTER returned_good_quantity,
            ADD COLUMN lost_quantity INT NOT NULL DEFAULT 0 AFTER returned_damaged_quantity,
            ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS equipment_stock_movements (
            movement_id INT AUTO_INCREMENT PRIMARY KEY,
            item_id INT NOT NULL,
            movement_type ENUM(
                'Stock Added',
                'Stock Adjustment',
                'Issued',
                'Returned Good',
                'Returned Damaged',
                'Moved to Maintenance',
                'Repaired',
                'Lost',
                'Recovered'
            ) NOT NULL,
            quantity INT NOT NULL,
            booking_id INT NULL,
            user_id INT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT NULL,
            INDEX idx_test_mov_item (item_id),
            INDEX idx_test_mov_booking (booking_id),
            INDEX idx_test_mov_type (movement_type),
            CONSTRAINT fk_test_stock_movement_item FOREIGN KEY (item_id) REFERENCES equipment_items(item_id) ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT fk_test_stock_movement_booking FOREIGN KEY (booking_id) REFERENCES bookings(booking_id) ON DELETE SET NULL ON UPDATE CASCADE,
            CONSTRAINT fk_test_stock_movement_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL ON UPDATE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)

    cursor.execute("SHOW COLUMNS FROM users LIKE 'token_version'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE users ADD COLUMN token_version INT NOT NULL DEFAULT 1 AFTER is_active")

    cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
    conn.commit()

    # Seed mock fixtures
    p_hash = get_password_hash("Password123!")

    # 1. Departments
    cursor.execute("INSERT INTO departments (department_id, department_name, is_active) VALUES (1, 'Computer Science', 1), (2, 'Electronics', 1)")

    # 2. Categories
    cursor.execute("INSERT INTO categories (category_id, category_name) VALUES (1, 'Classroom'), (2, 'Auditorium')")

    # 3. Resources
    cursor.execute("""
        INSERT INTO resources (resource_id, category_id, resource_name, resource_code, location, capacity, status)
        VALUES
        (1, 1, 'Lab 101', 'LAB-101', 'Block A, 1st Floor', 40, 'Available'),
        (2, 2, 'Main Auditorium', 'AUD-01', 'Main Admin Block', 500, 'Available'),
        (3, 1, 'Studio 301', 'STU-301', 'Block C, 3rd Floor', 30, 'Maintenance'),
        (4, 1, 'Inactive Hall', 'INA-999', 'Old Block', 20, 'Inactive')
    """)

    # 4. Users
    cursor.execute(f"""
        INSERT INTO users (user_id, department_id, name, email, password_hash, role, is_active)
        VALUES
        (1, 1, 'Admin Tester', 'admin.test@campus.edu', '{p_hash}', 'Admin', 1),
        (2, 1, 'Faculty Tester', 'faculty.test@campus.edu', '{p_hash}', 'Faculty', 1),
        (3, 1, 'Staff Tester', 'staff.test@campus.edu', '{p_hash}', 'Staff', 1),
        (4, 1, 'Student Tester', 'student.test@campus.edu', '{p_hash}', 'Student', 1),
        (5, 1, 'Inactive Tester', 'inactive.student@campus.edu', '{p_hash}', 'Student', 0)
    """)

    # 5. Societies
    cursor.execute("""
        INSERT INTO societies (club_id, department_id, club_name, description, is_active, created_by)
        VALUES (1, 1, 'Robotics Club', 'Autonomous robotics and electronics club', 1, 1)
    """)

    cursor.execute("""
        INSERT INTO society_members (club_member_id, club_id, user_id, member_role, can_manage, can_book, is_active)
        VALUES
        (1, 1, 4, 'President', 1, 1, 1)
    """)

    # 6. Equipment items
    cursor.execute("""
        INSERT INTO equipment_items (
            item_id, item_code, item_name, category, description, unit,
            total_quantity, damaged_quantity, maintenance_quantity, lost_quantity, location, is_active
        )
        VALUES
        (1, 'AV-PRJ-01', 'Digital Projector Pro', 'Audio/Visual', 'Multimedia projector', 'Piece', 6, 0, 0, 0, 'Gym', 1),
        (2, 'SPT-BAD-01', 'Badminton Racket', 'Sports', 'Tournament badminton racket', 'Piece', 5, 0, 5, 0, 'Gym', 1),
        (3, 'SPT-FTB-01', 'Football', 'Sports', 'Size 5 match football', 'Piece', 10, 0, 0, 0, 'Gym', 1),
        (4, 'AV-MIC-99', 'Deactivated Mic', 'Audio/Visual', 'Old microphone model', 'Piece', 5, 0, 0, 0, 'Gym', 0)
    """)

    # 7. Recurring academic timetable entry
    cursor.execute("""
        INSERT INTO resource_timetable (resource_id, day_of_week, start_time, end_time, subject_name, department_name, academic_year)
        VALUES (1, 'Monday', '09:00:00', '11:00:00', 'Data Structures Lab', 'CSE', '2026-2027')
    """)

    conn.commit()
    cursor.close()
    conn.close()
    print("Isolated test database 'smart_campus_test' initialized and seeded successfully!")


if __name__ == "__main__":
    setup_isolated_test_database()
