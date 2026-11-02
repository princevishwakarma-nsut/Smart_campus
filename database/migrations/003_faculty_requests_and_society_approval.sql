-- Migration 003: Faculty Registration Requests and Society Approval Workflow
-- Non-destructive schema updates preserving all existing campus records.

-- 1. Create faculty_requests table
CREATE TABLE IF NOT EXISTS faculty_requests (
    request_id INT AUTO_INCREMENT PRIMARY KEY,
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
    CONSTRAINT fk_faculty_req_dept FOREIGN KEY (department_id) REFERENCES departments(department_id) ON DELETE SET NULL,
    CONSTRAINT fk_faculty_req_reviewer FOREIGN KEY (reviewed_by) REFERENCES users(user_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Add approval columns to societies table
ALTER TABLE societies
ADD COLUMN IF NOT EXISTS status ENUM('Pending', 'Approved', 'Rejected') NOT NULL DEFAULT 'Approved',
ADD COLUMN IF NOT EXISTS rejection_reason VARCHAR(255) NULL,
ADD COLUMN IF NOT EXISTS reviewed_by INT NULL,
ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP NULL;
