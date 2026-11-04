CREATE TABLE IF NOT EXISTS equipment_blackout_periods (
    equipment_blackout_id INT NOT NULL AUTO_INCREMENT,
    item_id INT NOT NULL,
    blackout_group_id VARCHAR(36) NOT NULL,
    start_datetime DATETIME NOT NULL,
    end_datetime DATETIME NOT NULL,
    reason_category VARCHAR(50) NOT NULL DEFAULT 'Other',
    reason_explanation TEXT NOT NULL,
    status ENUM('Active', 'Cancelled') NOT NULL DEFAULT 'Active',
    created_by INT NOT NULL,
    cancelled_by INT NULL,
    cancelled_at DATETIME NULL,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (equipment_blackout_id),
    KEY idx_equipment_blackout_group (blackout_group_id),
    KEY idx_equipment_blackout_item_dates (item_id, start_datetime, end_datetime),
    KEY idx_equipment_blackout_status_dates (status, start_datetime, end_datetime),
    CONSTRAINT fk_equipment_blackout_item
        FOREIGN KEY (item_id) REFERENCES equipment_items (item_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_equipment_blackout_creator
        FOREIGN KEY (created_by) REFERENCES users (user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_equipment_blackout_cancelled_by
        FOREIGN KEY (cancelled_by) REFERENCES users (user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_equipment_blackout_dates CHECK (end_datetime > start_datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
