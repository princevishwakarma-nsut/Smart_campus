CREATE TABLE IF NOT EXISTS resource_operating_hours (
    operating_hours_id BIGINT NOT NULL AUTO_INCREMENT,
    resource_id INT NOT NULL,
    weekday TINYINT UNSIGNED NOT NULL,
    is_closed TINYINT(1) NOT NULL DEFAULT 0,
    open_time TIME NULL,
    close_time TIME NULL,
    updated_by INT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (operating_hours_id),
    UNIQUE KEY uq_resource_operating_weekday (resource_id, weekday),
    KEY idx_resource_operating_resource (resource_id),
    CONSTRAINT fk_resource_operating_resource FOREIGN KEY (resource_id)
        REFERENCES resources (resource_id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_resource_operating_user FOREIGN KEY (updated_by)
        REFERENCES users (user_id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS resource_operating_hour_exceptions (
    exception_id BIGINT NOT NULL AUTO_INCREMENT,
    resource_id INT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    is_closed TINYINT(1) NOT NULL DEFAULT 1,
    open_time TIME NULL,
    close_time TIME NULL,
    reason VARCHAR(255) NOT NULL,
    status ENUM('Active', 'Cancelled') NOT NULL DEFAULT 'Active',
    created_by INT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cancelled_by INT NULL,
    cancelled_at DATETIME NULL,
    PRIMARY KEY (exception_id),
    KEY idx_operating_exception_resource_dates (resource_id, status, start_date, end_date),
    CONSTRAINT fk_operating_exception_resource FOREIGN KEY (resource_id)
        REFERENCES resources (resource_id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_operating_exception_creator FOREIGN KEY (created_by)
        REFERENCES users (user_id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_operating_exception_canceller FOREIGN KEY (cancelled_by)
        REFERENCES users (user_id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE maintenance_records
    ADD COLUMN maintenance_type VARCHAR(40) NULL AFTER issue_description;
