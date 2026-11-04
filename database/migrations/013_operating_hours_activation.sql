ALTER TABLE resource_operating_hours
    ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 1 AFTER close_time;
