-- Migration 001: Add maintenance_id to resource_blackout_periods & create system_audit
-- Database: smart_campus

-- 1. Add nullable maintenance_id column to resource_blackout_periods with ON DELETE RESTRICT
ALTER TABLE resource_blackout_periods
  ADD COLUMN maintenance_id INT NULL AFTER resource_id,
  ADD CONSTRAINT fk_blackout_maintenance
    FOREIGN KEY (maintenance_id)
    REFERENCES maintenance_records(maintenance_id)
    ON UPDATE CASCADE
    ON DELETE RESTRICT;

-- 2. Create append-only system_audit table with indexes on entity, changed_by, and created_at
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
