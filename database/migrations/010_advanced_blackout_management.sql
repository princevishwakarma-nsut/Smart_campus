ALTER TABLE resource_blackout_periods
    ADD COLUMN blackout_group_id VARCHAR(36) NULL AFTER maintenance_id,
    ADD COLUMN reason_category VARCHAR(50) NOT NULL DEFAULT 'Other' AFTER reason,
    ADD COLUMN reason_explanation TEXT NULL AFTER reason_category,
    ADD COLUMN category_ids JSON NULL AFTER reason_explanation,
    ADD COLUMN status ENUM('Active', 'Cancelled') NOT NULL DEFAULT 'Active' AFTER category_ids,
    ADD COLUMN cancelled_by INT NULL AFTER status,
    ADD COLUMN cancelled_at DATETIME NULL AFTER cancelled_by,
    ADD KEY idx_blackout_group (blackout_group_id),
    ADD KEY idx_blackout_status_dates (status, start_datetime, end_datetime),
    ADD CONSTRAINT fk_blackout_cancelled_by FOREIGN KEY (cancelled_by)
        REFERENCES users (user_id) ON DELETE RESTRICT ON UPDATE CASCADE;

UPDATE resource_blackout_periods
SET reason_category = CASE
    WHEN maintenance_id IS NOT NULL THEN 'Maintenance'
    ELSE 'Other'
END,
reason_explanation = reason;
