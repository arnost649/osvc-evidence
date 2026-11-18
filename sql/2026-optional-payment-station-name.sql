-- Preserve all historical values; custom names do not overwrite legacy branches.
ALTER TABLE payments MODIFY method ENUM('bank','cash','card','other') NULL DEFAULT NULL;
ALTER TABLE fuel_purchases ADD COLUMN station_name VARCHAR(200) NULL AFTER station;
