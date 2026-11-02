CREATE TABLE IF NOT EXISTS system_settings (
  setting_id TINYINT NOT NULL PRIMARY KEY,
  academic_year VARCHAR(9) NOT NULL DEFAULT '2026-2027',
  timetable_enforcement TINYINT(1) NOT NULL DEFAULT 1,
  booking_window_days INT NOT NULL DEFAULT 30,
  approval_mode ENUM('Manual', 'ByCategory') NOT NULL DEFAULT 'Manual',
  approval_categories JSON NOT NULL,
  min_booking_minutes INT NOT NULL DEFAULT 15,
  max_booking_minutes INT NOT NULL DEFAULT 480,
  cancellation_cutoff_hours INT NOT NULL DEFAULT 0,
  updated_by INT DEFAULT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_system_settings_updated_by FOREIGN KEY (updated_by)
    REFERENCES users (user_id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO system_settings (
  setting_id, academic_year, timetable_enforcement, booking_window_days,
  approval_mode, approval_categories, min_booking_minutes,
  max_booking_minutes, cancellation_cutoff_hours
) VALUES (1, '2026-2027', 1, 30, 'Manual', JSON_ARRAY(), 15, 480, 0);
