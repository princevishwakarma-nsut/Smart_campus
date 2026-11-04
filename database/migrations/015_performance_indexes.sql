-- Migration 015: Performance indexes for Aiven Cloud MySQL latency optimization
-- Speeds up date-range queries, status filtering, and audit trail sorting

CREATE INDEX IF NOT EXISTS idx_blackout_start_id ON resource_blackout_periods (start_datetime DESC, blackout_id DESC);
CREATE INDEX IF NOT EXISTS idx_bookings_start_status ON bookings (start_time, status);
CREATE INDEX IF NOT EXISTS idx_bookings_created_at ON bookings (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_booking_audit_changed_at ON booking_audit (changed_at DESC, audit_id DESC);
CREATE INDEX IF NOT EXISTS idx_equipment_active_category ON equipment_items (is_active, category, item_name);
