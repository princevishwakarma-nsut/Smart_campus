-- Migration 007: Separate administrator notifications from user notifications.

ALTER TABLE notifications
ADD COLUMN audience ENUM('User', 'Admin') NOT NULL DEFAULT 'User' AFTER user_id;

UPDATE notifications n
JOIN users u ON u.user_id = n.user_id
SET n.audience = 'Admin'
WHERE u.role = 'Admin'
  AND n.message LIKE 'New booking request BK-% requires your approval.%';

CREATE INDEX idx_notifications_user_audience_read
ON notifications (user_id, audience, is_read);
