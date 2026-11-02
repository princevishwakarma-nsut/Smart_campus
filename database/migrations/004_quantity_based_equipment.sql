-- ============================================================================
-- Migration 004: Quantity-Based Sports & Electronic Equipment Inventory System
-- ============================================================================

-- 1. Archive legacy equipment items for historical reference
CREATE TABLE IF NOT EXISTS equipment_items_legacy AS SELECT * FROM equipment_items;

-- 2. Add start_time and end_time to bookings (supports equipment-only bookings)
ALTER TABLE bookings
ADD COLUMN IF NOT EXISTS start_time DATETIME NULL,
ADD COLUMN IF NOT EXISTS end_time DATETIME NULL;

-- Backfill bookings start_time and end_time from existing booking_resources
UPDATE bookings b
JOIN (
    SELECT booking_id, MIN(start_time) AS min_s, MAX(end_time) AS max_e
    FROM booking_resources
    GROUP BY booking_id
) br ON b.booking_id = br.booking_id
SET b.start_time = br.min_s, b.end_time = br.max_e
WHERE b.start_time IS NULL;

-- 3. Modify equipment_items table to quantity-based structure
-- First add new columns
ALTER TABLE equipment_items
ADD COLUMN IF NOT EXISTS item_code VARCHAR(50) NULL AFTER item_id,
ADD COLUMN IF NOT EXISTS category ENUM('Sports', 'Electronics', 'Audio/Visual', 'IT', 'Accessories', 'Other') NOT NULL DEFAULT 'Other' AFTER item_name,
ADD COLUMN IF NOT EXISTS unit VARCHAR(50) NOT NULL DEFAULT 'Piece' AFTER description,
ADD COLUMN IF NOT EXISTS total_quantity INT NOT NULL DEFAULT 1 AFTER unit,
ADD COLUMN IF NOT EXISTS damaged_quantity INT NOT NULL DEFAULT 0 AFTER total_quantity,
ADD COLUMN IF NOT EXISTS maintenance_quantity INT NOT NULL DEFAULT 0 AFTER damaged_quantity,
ADD COLUMN IF NOT EXISTS lost_quantity INT NOT NULL DEFAULT 0 AFTER maintenance_quantity,
ADD COLUMN IF NOT EXISTS is_active TINYINT(1) NOT NULL DEFAULT 1 AFTER purchase_date,
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP AFTER created_at;

-- Populate item_code and default Gym location for existing rows
UPDATE equipment_items
SET item_code = CONCAT('EQ-', LPAD(item_id, 3, '0')),
    location = 'Gym',
    category = 'Audio/Visual'
WHERE item_code IS NULL;

-- Normalize any legacy rows and keep new inserts compatible with old data entry paths.
ALTER TABLE equipment_items
MODIFY COLUMN item_code VARCHAR(50) NULL,
ADD UNIQUE KEY IF NOT EXISTS uq_equipment_item_code (item_code);

UPDATE equipment_items
SET item_code = CONCAT('EQ-', LPAD(item_id, 3, '0'))
WHERE item_code IS NULL OR TRIM(item_code) = '';

ALTER TABLE equipment_items
MODIFY COLUMN item_code VARCHAR(50) NOT NULL;

DROP TRIGGER IF EXISTS trg_equipment_item_code_default_insert;
CREATE TRIGGER trg_equipment_item_code_default_insert
BEFORE INSERT ON equipment_items
FOR EACH ROW
BEGIN
    IF NEW.item_code IS NULL OR TRIM(NEW.item_code) = '' THEN
        SET NEW.item_code = CONCAT('EQ-', UPPER(SUBSTRING(REPLACE(UUID(), '-', ''), 1, 8)));
    END IF;
END;

DROP TRIGGER IF EXISTS trg_equipment_item_code_default_update;
CREATE TRIGGER trg_equipment_item_code_default_update
BEFORE UPDATE ON equipment_items
FOR EACH ROW
BEGIN
    IF NEW.item_code IS NULL OR TRIM(NEW.item_code) = '' THEN
        SET NEW.item_code = CONCAT('EQ-', UPPER(SUBSTRING(REPLACE(UUID(), '-', ''), 1, 8)));
    END IF;
END;

-- 4. Redesign booking_equipment_items for quantity reservations
-- If old columns exist, alter them to quantity structure
ALTER TABLE booking_equipment_items
ADD COLUMN IF NOT EXISTS requested_quantity INT NOT NULL DEFAULT 1 AFTER item_id,
ADD COLUMN IF NOT EXISTS approved_quantity INT NOT NULL DEFAULT 0 AFTER requested_quantity,
ADD COLUMN IF NOT EXISTS issued_quantity INT NOT NULL DEFAULT 0 AFTER approved_quantity,
ADD COLUMN IF NOT EXISTS returned_good_quantity INT NOT NULL DEFAULT 0 AFTER issued_quantity,
ADD COLUMN IF NOT EXISTS returned_damaged_quantity INT NOT NULL DEFAULT 0 AFTER returned_good_quantity,
ADD COLUMN IF NOT EXISTS lost_quantity INT NOT NULL DEFAULT 0 AFTER returned_damaged_quantity,
ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP;

-- 5. Create equipment_stock_movements table
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
