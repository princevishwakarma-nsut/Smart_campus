-- Migration 006: Persistent session invalidation via token_version on users table
-- Ensures logout, password changes, admin password resets, and account deactivations
-- invalidate JWT sessions across backend restarts.

ALTER TABLE users 
ADD COLUMN IF NOT EXISTS token_version INT NOT NULL DEFAULT 1 AFTER is_active;
