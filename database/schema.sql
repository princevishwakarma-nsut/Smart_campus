-- Smart Campus Database Schema Dump
-- Database: smart_campus
-- Academic Year: 2026-2027

CREATE DATABASE IF NOT EXISTS smart_campus CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE smart_campus;

SET FOREIGN_KEY_CHECKS = 0;

-- Table structure for booking_approvals
DROP TABLE IF EXISTS booking_approvals;
CREATE TABLE `booking_approvals` (
  `approval_id` int NOT NULL AUTO_INCREMENT,
  `booking_id` int NOT NULL,
  `booking_resource_id` int DEFAULT NULL,
  `approver_id` int NOT NULL,
  `decision` enum('Approved','Rejected') NOT NULL,
  `remarks` text,
  `decided_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`approval_id`),
  KEY `fk_approvals_booking` (`booking_id`),
  KEY `fk_approvals_booking_resource` (`booking_resource_id`),
  KEY `idx_approvals_approver` (`approver_id`),
  CONSTRAINT `fk_approvals_approver` FOREIGN KEY (`approver_id`) REFERENCES `users` (`user_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_approvals_booking` FOREIGN KEY (`booking_id`) REFERENCES `bookings` (`booking_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_approvals_booking_resource` FOREIGN KEY (`booking_resource_id`) REFERENCES `booking_resources` (`booking_resource_id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for booking_audit
DROP TABLE IF EXISTS booking_audit;
CREATE TABLE `booking_audit` (
  `audit_id` int NOT NULL AUTO_INCREMENT,
  `booking_id` int NOT NULL,
  `changed_by` int NOT NULL,
  `action` varchar(100) NOT NULL,
  `old_values` json DEFAULT NULL,
  `new_values` json DEFAULT NULL,
  `remarks` text,
  `changed_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`audit_id`),
  KEY `fk_audit_user` (`changed_by`),
  KEY `idx_audit_booking` (`booking_id`,`changed_at`),
  CONSTRAINT `fk_audit_booking` FOREIGN KEY (`booking_id`) REFERENCES `bookings` (`booking_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_audit_user` FOREIGN KEY (`changed_by`) REFERENCES `users` (`user_id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for booking_equipment_items
DROP TABLE IF EXISTS booking_equipment_items;
CREATE TABLE `booking_equipment_items` (
  `booking_equipment_id` int NOT NULL AUTO_INCREMENT,
  `booking_id` int NOT NULL,
  `item_id` int NOT NULL,
  `issued_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `returned_at` datetime DEFAULT NULL,
  `condition_on_return` enum('Good','Damaged') DEFAULT NULL,
  PRIMARY KEY (`booking_equipment_id`),
  UNIQUE KEY `uq_booking_equipment` (`booking_id`,`item_id`),
  KEY `fk_booking_equipment_item` (`item_id`),
  CONSTRAINT `fk_booking_equipment_booking` FOREIGN KEY (`booking_id`) REFERENCES `bookings` (`booking_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_booking_equipment_item` FOREIGN KEY (`item_id`) REFERENCES `equipment_items` (`item_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `chk_equipment_return_date` CHECK (((`returned_at` is null) or (`returned_at` >= `issued_at`)))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for booking_participants
DROP TABLE IF EXISTS booking_participants;
CREATE TABLE `booking_participants` (
  `booking_participant_id` int NOT NULL AUTO_INCREMENT,
  `booking_id` int NOT NULL,
  `user_id` int NOT NULL,
  `participant_role` enum('Organizer','Participant','Volunteer') NOT NULL DEFAULT 'Participant',
  `attendance_status` enum('Invited','Attending','Declined') NOT NULL DEFAULT 'Invited',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`booking_participant_id`),
  UNIQUE KEY `uq_booking_participant` (`booking_id`,`user_id`),
  KEY `idx_participants_user` (`user_id`),
  CONSTRAINT `fk_participants_booking` FOREIGN KEY (`booking_id`) REFERENCES `bookings` (`booking_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_participants_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for booking_resources
DROP TABLE IF EXISTS booking_resources;
CREATE TABLE `booking_resources` (
  `booking_resource_id` int NOT NULL AUTO_INCREMENT,
  `booking_id` int NOT NULL,
  `resource_id` int NOT NULL,
  `start_time` datetime NOT NULL,
  `end_time` datetime NOT NULL,
  `status` enum('Pending','Approved','Rejected','Cancelled') NOT NULL DEFAULT 'Pending',
  PRIMARY KEY (`booking_resource_id`),
  KEY `fk_booking_resources_booking` (`booking_id`),
  KEY `idx_booking_resource_slot` (`resource_id`,`start_time`,`end_time`,`status`),
  CONSTRAINT `fk_booking_resources_booking` FOREIGN KEY (`booking_id`) REFERENCES `bookings` (`booking_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_booking_resources_resource` FOREIGN KEY (`resource_id`) REFERENCES `resources` (`resource_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `chk_booking_resource_dates` CHECK ((`end_time` > `start_time`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for bookings
DROP TABLE IF EXISTS bookings;
CREATE TABLE `bookings` (
  `booking_id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `society_id` int DEFAULT NULL,
  `purpose` varchar(255) NOT NULL,
  `expected_participants` int NOT NULL DEFAULT '1',
  `status` enum('Pending','Approved','Rejected','Cancelled') NOT NULL DEFAULT 'Pending',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`booking_id`),
  KEY `idx_bookings_user` (`user_id`),
  KEY `idx_bookings_club` (`society_id`),
  KEY `idx_bookings_status` (`status`),
  CONSTRAINT `fk_bookings_club` FOREIGN KEY (`society_id`) REFERENCES `societies` (`club_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_bookings_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `chk_expected_participants` CHECK ((`expected_participants` > 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for categories
DROP TABLE IF EXISTS categories;
CREATE TABLE `categories` (
  `category_id` int NOT NULL AUTO_INCREMENT,
  `category_name` varchar(100) NOT NULL,
  `description` text,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`category_id`),
  UNIQUE KEY `category_name` (`category_name`)
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for checkins
DROP TABLE IF EXISTS checkins;
CREATE TABLE `checkins` (
  `checkin_id` int NOT NULL AUTO_INCREMENT,
  `booking_participant_id` int NOT NULL,
  `verified_by` int NOT NULL,
  `checkin_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `checkout_time` datetime DEFAULT NULL,
  `status` enum('Checked-in','Checked-out','No-show') NOT NULL DEFAULT 'Checked-in',
  `remarks` text,
  PRIMARY KEY (`checkin_id`),
  UNIQUE KEY `booking_participant_id` (`booking_participant_id`),
  KEY `fk_checkins_verifier` (`verified_by`),
  CONSTRAINT `fk_checkins_participant` FOREIGN KEY (`booking_participant_id`) REFERENCES `booking_participants` (`booking_participant_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_checkins_verifier` FOREIGN KEY (`verified_by`) REFERENCES `users` (`user_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `chk_checkin_checkout` CHECK (((`checkout_time` is null) or (`checkout_time` >= `checkin_time`)))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for departments
DROP TABLE IF EXISTS departments;
CREATE TABLE `departments` (
  `department_id` int NOT NULL AUTO_INCREMENT,
  `department_name` varchar(100) NOT NULL,
  `description` text,
  `hod_user_id` int DEFAULT NULL,
  `office_location` varchar(150) DEFAULT NULL,
  `contact_email` varchar(150) DEFAULT NULL,
  `contact_phone` varchar(20) DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  PRIMARY KEY (`department_id`),
  UNIQUE KEY `department_name` (`department_name`),
  KEY `fk_departments_hod` (`hod_user_id`),
  CONSTRAINT `fk_departments_hod` FOREIGN KEY (`hod_user_id`) REFERENCES `users` (`user_id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for equipment_items
DROP TABLE IF EXISTS equipment_items;
CREATE TABLE `equipment_items` (
  `item_id` int NOT NULL AUTO_INCREMENT,
  `item_code` varchar(50) DEFAULT NULL,
  `item_name` varchar(150) NOT NULL,
  `serial_no` varchar(100) DEFAULT NULL,
  `condition_status` enum('Good','Damaged') NOT NULL DEFAULT 'Good',
  `availability_status` enum('Available','Issued','Maintenance') NOT NULL DEFAULT 'Available',
  `location` varchar(200) DEFAULT NULL,
  `purchase_date` date DEFAULT NULL,
  `warranty_expiry` date DEFAULT NULL,
  `description` text,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`item_id`),
  UNIQUE KEY `serial_no` (`serial_no`),
  UNIQUE KEY `uq_equipment_item_code` (`item_code`),
  KEY `idx_equipment_status` (`availability_status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for maintenance_records
DROP TABLE IF EXISTS maintenance_records;
CREATE TABLE `maintenance_records` (
  `maintenance_id` int NOT NULL AUTO_INCREMENT,
  `resource_id` int DEFAULT NULL,
  `item_id` int DEFAULT NULL,
  `reported_by` int NOT NULL,
  `assigned_to` int DEFAULT NULL,
  `issue_description` text NOT NULL,
  `status` enum('Open','In Progress','Resolved') NOT NULL DEFAULT 'Open',
  `reported_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `resolved_at` datetime DEFAULT NULL,
  `remarks` text,
  PRIMARY KEY (`maintenance_id`),
  KEY `fk_maintenance_resource` (`resource_id`),
  KEY `fk_maintenance_item` (`item_id`),
  KEY `fk_maintenance_reporter` (`reported_by`),
  KEY `fk_maintenance_assignee` (`assigned_to`),
  KEY `idx_maintenance_status` (`status`),
  CONSTRAINT `fk_maintenance_assignee` FOREIGN KEY (`assigned_to`) REFERENCES `users` (`user_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_maintenance_item` FOREIGN KEY (`item_id`) REFERENCES `equipment_items` (`item_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_maintenance_reporter` FOREIGN KEY (`reported_by`) REFERENCES `users` (`user_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_maintenance_resource` FOREIGN KEY (`resource_id`) REFERENCES `resources` (`resource_id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for notifications
DROP TABLE IF EXISTS notifications;
CREATE TABLE `notifications` (
  `notification_id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `audience` enum('User','Admin') NOT NULL DEFAULT 'User',
  `booking_id` int DEFAULT NULL,
  `message` text NOT NULL,
  `type` enum('Info','Reminder','Approval','Alert') NOT NULL DEFAULT 'Info',
  `is_read` tinyint(1) NOT NULL DEFAULT '0',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`notification_id`),
  KEY `fk_notifications_booking` (`booking_id`),
  KEY `idx_notifications_user_read` (`user_id`,`is_read`),
  KEY `idx_notifications_user_audience_read` (`user_id`,`audience`,`is_read`),
  CONSTRAINT `fk_notifications_booking` FOREIGN KEY (`booking_id`) REFERENCES `bookings` (`booking_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_notifications_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for resource_blackout_periods
DROP TABLE IF EXISTS resource_blackout_periods;
CREATE TABLE `resource_blackout_periods` (
  `blackout_id` int NOT NULL AUTO_INCREMENT,
  `resource_id` int NOT NULL,
  `start_datetime` datetime NOT NULL,
  `end_datetime` datetime NOT NULL,
  `reason` varchar(255) DEFAULT NULL,
  `created_by` int NOT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`blackout_id`),
  KEY `fk_blackout_creator` (`created_by`),
  KEY `idx_blackout_resource_dates` (`resource_id`,`start_datetime`,`end_datetime`),
  CONSTRAINT `fk_blackout_creator` FOREIGN KEY (`created_by`) REFERENCES `users` (`user_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_blackout_resource` FOREIGN KEY (`resource_id`) REFERENCES `resources` (`resource_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `chk_blackout_dates` CHECK ((`end_datetime` > `start_datetime`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for resource_features
DROP TABLE IF EXISTS resource_features;
CREATE TABLE `resource_features` (
  `feature_id` int NOT NULL AUTO_INCREMENT,
  `resource_id` int NOT NULL,
  `feature_name` varchar(100) NOT NULL,
  `description` text,
  PRIMARY KEY (`feature_id`),
  UNIQUE KEY `uq_resource_feature` (`resource_id`,`feature_name`),
  CONSTRAINT `fk_features_resource` FOREIGN KEY (`resource_id`) REFERENCES `resources` (`resource_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=16 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for resource_timetable
DROP TABLE IF EXISTS resource_timetable;
CREATE TABLE `resource_timetable` (
  `timetable_id` int NOT NULL AUTO_INCREMENT,
  `resource_id` int NOT NULL,
  `department_name` varchar(100) DEFAULT NULL,
  `section` varchar(50) DEFAULT NULL,
  `subject_name` varchar(150) DEFAULT NULL,
  `day_of_week` enum('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday') NOT NULL,
  `start_time` time NOT NULL,
  `end_time` time NOT NULL,
  `academic_year` varchar(20) DEFAULT NULL,
  `semester` varchar(30) DEFAULT NULL,
  `class_type` enum('Theory','Tutorial','Lab') NOT NULL DEFAULT 'Theory',
  PRIMARY KEY (`timetable_id`),
  KEY `idx_resource_id` (`resource_id`),
  CONSTRAINT `fk_timetable_resource` FOREIGN KEY (`resource_id`) REFERENCES `resources` (`resource_id`)
) ENGINE=InnoDB AUTO_INCREMENT=487 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for resources
DROP TABLE IF EXISTS resources;
CREATE TABLE `resources` (
  `resource_id` int NOT NULL AUTO_INCREMENT,
  `category_id` int NOT NULL,
  `resource_name` varchar(150) NOT NULL,
  `resource_code` varchar(50) NOT NULL,
  `location` varchar(200) NOT NULL,
  `capacity` int DEFAULT NULL,
  `status` enum('Available','Maintenance','Inactive') NOT NULL DEFAULT 'Available',
  `description` text,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`resource_id`),
  UNIQUE KEY `resource_code` (`resource_code`),
  KEY `idx_resources_category_status` (`category_id`,`status`),
  CONSTRAINT `fk_resources_category` FOREIGN KEY (`category_id`) REFERENCES `categories` (`category_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `chk_resource_capacity` CHECK (((`capacity` is null) or (`capacity` >= 0)))
) ENGINE=InnoDB AUTO_INCREMENT=32 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for societies
DROP TABLE IF EXISTS societies;
CREATE TABLE `societies` (
  `club_id` int NOT NULL AUTO_INCREMENT,
  `department_id` int DEFAULT NULL,
  `club_name` varchar(100) NOT NULL,
  `description` text,
  `faculty_coordinator_id` int DEFAULT NULL,
  `created_by` int NOT NULL,
  `established_year` smallint DEFAULT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`club_id`),
  UNIQUE KEY `club_name` (`club_name`),
  KEY `fk_clubs_creator` (`created_by`),
  KEY `idx_clubs_department` (`department_id`),
  KEY `idx_clubs_coordinator` (`faculty_coordinator_id`),
  CONSTRAINT `fk_clubs_coordinator` FOREIGN KEY (`faculty_coordinator_id`) REFERENCES `users` (`user_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_clubs_creator` FOREIGN KEY (`created_by`) REFERENCES `users` (`user_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_clubs_department` FOREIGN KEY (`department_id`) REFERENCES `departments` (`department_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_club_year` CHECK (((`established_year` is null) or (`established_year` between 1900 and 2100)))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for society_members
DROP TABLE IF EXISTS society_members;
CREATE TABLE `society_members` (
  `club_member_id` int NOT NULL AUTO_INCREMENT,
  `club_id` int NOT NULL,
  `user_id` int NOT NULL,
  `member_role` enum('President','Vice President','Secretary','Treasurer','Coordinator','Member') NOT NULL DEFAULT 'Member',
  `can_manage` tinyint(1) NOT NULL DEFAULT '0',
  `can_book` tinyint(1) NOT NULL DEFAULT '0',
  `joined_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  PRIMARY KEY (`club_member_id`),
  UNIQUE KEY `uq_club_member` (`club_id`,`user_id`),
  KEY `idx_members_user` (`user_id`),
  CONSTRAINT `fk_members_club` FOREIGN KEY (`club_id`) REFERENCES `societies` (`club_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_members_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table structure for users
DROP TABLE IF EXISTS users;
CREATE TABLE `users` (
  `user_id` int NOT NULL AUTO_INCREMENT,
  `department_id` int DEFAULT NULL,
  `name` varchar(100) NOT NULL,
  `email` varchar(150) NOT NULL,
  `password_hash` varchar(255) NOT NULL,
  `role` enum('Student','Faculty','Admin','Staff') NOT NULL DEFAULT 'Student',
  `phone_no` varchar(20) DEFAULT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `email` (`email`),
  KEY `idx_users_department` (`department_id`),
  KEY `idx_users_role` (`role`),
  CONSTRAINT `fk_users_department` FOREIGN KEY (`department_id`) REFERENCES `departments` (`department_id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE IF NOT EXISTS `system_settings` (
  `setting_id` tinyint NOT NULL,
  `academic_year` varchar(9) NOT NULL DEFAULT '2026-2027',
  `timetable_enforcement` tinyint(1) NOT NULL DEFAULT '1',
  `booking_window_days` int NOT NULL DEFAULT '30',
  `approval_mode` enum('Manual','ByCategory') NOT NULL DEFAULT 'Manual',
  `approval_categories` json NOT NULL,
  `min_booking_minutes` int NOT NULL DEFAULT '15',
  `max_booking_minutes` int NOT NULL DEFAULT '480',
  `cancellation_cutoff_hours` int NOT NULL DEFAULT '0',
  `updated_by` int DEFAULT NULL,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`setting_id`),
  KEY `fk_system_settings_updated_by` (`updated_by`),
  CONSTRAINT `fk_system_settings_updated_by` FOREIGN KEY (`updated_by`) REFERENCES `users` (`user_id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO `system_settings` (
  `setting_id`, `academic_year`, `timetable_enforcement`, `booking_window_days`,
  `approval_mode`, `approval_categories`, `min_booking_minutes`,
  `max_booking_minutes`, `cancellation_cutoff_hours`
) VALUES (1, '2026-2027', 1, 30, 'Manual', JSON_ARRAY(), 15, 480, 0);
