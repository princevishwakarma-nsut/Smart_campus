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


def apply_migration_004(target_db=None):
    database_name = target_db or db_name
    print(f"Applying Migration 004 to database: {database_name}...")
    conn = mysql.connector.connect(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_password,
        database=database_name
    )
    cursor = conn.cursor(dictionary=True)

    # 1. Archive legacy equipment items table
    cursor.execute("SHOW TABLES LIKE 'equipment_items_legacy'")
    if not cursor.fetchone():
        print("Archiving legacy equipment_items into equipment_items_legacy...")
        cursor.execute("CREATE TABLE equipment_items_legacy AS SELECT * FROM equipment_items")
        conn.commit()

    # 2. Add start_time and end_time to bookings if not present
    cursor.execute("SHOW COLUMNS FROM bookings LIKE 'start_time'")
    if not cursor.fetchone():
        print("Adding start_time and end_time columns to bookings...")
        cursor.execute("""
            ALTER TABLE bookings
            ADD COLUMN start_time DATETIME NULL,
            ADD COLUMN end_time DATETIME NULL
        """)
        conn.commit()

        # Backfill bookings start_time and end_time from existing booking_resources
        cursor.execute("""
            UPDATE bookings b
            JOIN (
                SELECT booking_id, MIN(start_time) AS min_s, MAX(end_time) AS max_e
                FROM booking_resources
                GROUP BY booking_id
            ) br ON b.booking_id = br.booking_id
            SET b.start_time = br.min_s, b.end_time = br.max_e
            WHERE b.start_time IS NULL
        """)
        conn.commit()
        print("Backfilled start_time and end_time in bookings.")

    # 3. Modify equipment_items to quantity-based structure
    cursor.execute("SHOW COLUMNS FROM equipment_items LIKE 'item_code'")
    if not cursor.fetchone():
        print("Altering equipment_items table to quantity-based inventory model...")
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
        conn.commit()

        # Update existing records with default item_code and category
        cursor.execute("""
            UPDATE equipment_items
            SET item_code = CONCAT('EQ-', LPAD(item_id, 3, '0')),
                location = 'Gym',
                category = 'Audio/Visual'
            WHERE item_code IS NULL
        """)
        conn.commit()

        # Keep the legacy inventory schema backward compatible while still enforcing uniqueness.
        cursor.execute("""
            ALTER TABLE equipment_items
            MODIFY COLUMN item_code VARCHAR(50) NULL,
            ADD UNIQUE KEY uq_equipment_item_code (item_code)
        """)
        cursor.execute("""
            UPDATE equipment_items
            SET item_code = CONCAT('EQ-', LPAD(item_id, 3, '0'))
            WHERE item_code IS NULL OR TRIM(item_code) = ''
        """)
        cursor.execute("""
            ALTER TABLE equipment_items
            MODIFY COLUMN item_code VARCHAR(50) NOT NULL
        """)
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
        conn.commit()
        print("equipment_items table altered successfully.")
    else:
        print("equipment_items already has item_code column.")

    # 4. Modify booking_equipment_items to quantity model
    cursor.execute("SHOW COLUMNS FROM booking_equipment_items LIKE 'requested_quantity'")
    if not cursor.fetchone():
        print("Altering booking_equipment_items to quantity model...")
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
        conn.commit()
        print("booking_equipment_items altered successfully.")
    else:
        print("booking_equipment_items already has requested_quantity column.")

    # 5. Create equipment_stock_movements table
    cursor.execute("SHOW TABLES LIKE 'equipment_stock_movements'")
    if not cursor.fetchone():
        print("Creating equipment_stock_movements table...")
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
                INDEX idx_movement_item (item_id),
                INDEX idx_movement_booking (booking_id),
                INDEX idx_movement_type (movement_type),
                CONSTRAINT fk_stock_movement_item FOREIGN KEY (item_id) REFERENCES equipment_items(item_id) ON DELETE CASCADE ON UPDATE CASCADE,
                CONSTRAINT fk_stock_movement_booking FOREIGN KEY (booking_id) REFERENCES bookings(booking_id) ON DELETE SET NULL ON UPDATE CASCADE,
                CONSTRAINT fk_stock_movement_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        conn.commit()
        print("equipment_stock_movements table created successfully.")
    else:
        print("equipment_stock_movements table already exists.")

    cursor.close()
    conn.close()
    print("Migration 004 applied successfully.")


if __name__ == "__main__":
    apply_migration_004()
