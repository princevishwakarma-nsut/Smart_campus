ALTER TABLE resource_blackout_periods
    ADD COLUMN excluded_resource_ids JSON NULL AFTER category_ids;
