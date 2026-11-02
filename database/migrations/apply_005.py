"""
Migration 005:
1. Create table timetable_faculty_assignments for professor-specific timetable mappings.
2. Add category 'Sports Facility' to categories table.
3. Seed authentic sports facility resources (Sports Complex, Football Ground, Basketball Court, etc.).
Preserves all existing data, bookings, timetable, users, and audit records.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend"))
from app.database.connection import get_db_connection


def run_migration():
    print("Connecting to MySQL database...")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1. Create timetable_faculty_assignments table
        print("Creating table timetable_faculty_assignments if not exists...")
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
                CONSTRAINT fk_tfa_timetable FOREIGN KEY (timetable_id) REFERENCES resource_timetable(timetable_id) ON DELETE CASCADE,
                CONSTRAINT fk_tfa_faculty FOREIGN KEY (faculty_user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                CONSTRAINT fk_tfa_assigned_by FOREIGN KEY (assigned_by) REFERENCES users(user_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
        """)
        print("Table timetable_faculty_assignments ready.")

        # 2. Add Sports Facility category
        cursor.execute("SELECT category_id FROM categories WHERE category_name = 'Sports Facility'")
        cat_row = cursor.fetchone()
        if not cat_row:
            cursor.execute("""
                INSERT INTO categories (category_name, description)
                VALUES ('Sports Facility', 'Indoor and outdoor athletic facilities, sports courts, and grounds.')
            """)
            category_id = cursor.lastrowid
            print(f"Added category 'Sports Facility' (category_id: {category_id}).")
        else:
            category_id = cat_row["category_id"]
            print(f"Category 'Sports Facility' already exists (category_id: {category_id}).")

        # 3. Add real campus sports facilities under category_id
        sports_facilities = [
            ("Sports Complex", "SPT-CMPLX", "Campus Sports Area", 500, "Multi-purpose campus sports complex for university events, tournaments, and athletic programs."),
            ("Football Ground", "SPT-FTB-GRD", "Main Sports Field", 200, "Full-size campus football field with natural turf and perimeter seating."),
            ("Basketball Court", "SPT-BSK-CRT", "Sports Complex Outdoor", 50, "Standard outdoor basketball court equipped with night floodlights."),
            ("Volleyball Court", "SPT-VLB-CRT", "Sports Complex Outdoor", 40, "Outdoor clay and sand volleyball court."),
            ("Badminton Court", "SPT-BAD-CRT", "Indoor Sports Complex", 30, "Indoor synthetic/wooden court with tournament net and lighting."),
            ("Tennis Court", "SPT-TNS-CRT", "Sports Complex Outdoor", 30, "Synthetic hard tennis court with regulation perimeter fencing.")
        ]

        for name, code, loc, cap, desc in sports_facilities:
            cursor.execute("SELECT resource_id FROM resources WHERE resource_code = %s", (code,))
            existing = cursor.fetchone()
            if not existing:
                cursor.execute("""
                    INSERT INTO resources (category_id, resource_name, resource_code, location, capacity, status, description)
                    VALUES (%s, %s, %s, %s, %s, 'Available', %s)
                """, (category_id, name, code, loc, cap, desc))
                print(f"Added sports resource: '{name}' ({code}).")
            else:
                print(f"Sports resource '{name}' ({code}) already exists.")

        conn.commit()
        print("Migration 005 completed successfully.")
    except Exception as e:
        conn.rollback()
        print(f"Migration 005 failed: {e}")
        raise e
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    run_migration()
