-- Safe, idempotent PHM -> Address-book supplier relation.
SET @schema_name = DATABASE();

SELECT COUNT(*) INTO @has_counterparty_id
FROM information_schema.columns
WHERE table_schema=@schema_name AND table_name='fuel_purchases' AND column_name='counterparty_id';
SET @sql = IF(@has_counterparty_id=0,
  'ALTER TABLE fuel_purchases ADD COLUMN counterparty_id BIGINT UNSIGNED NULL AFTER vehicle_id',
  'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SELECT COUNT(*) INTO @has_counterparty_index
FROM information_schema.statistics
WHERE table_schema=@schema_name AND table_name='fuel_purchases' AND index_name='idx_fuel_counterparty';
SET @sql = IF(@has_counterparty_index=0,
  'ALTER TABLE fuel_purchases ADD KEY idx_fuel_counterparty (counterparty_id)',
  'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SELECT COUNT(*) INTO @has_counterparty_fk
FROM information_schema.referential_constraints
WHERE constraint_schema=@schema_name AND table_name='fuel_purchases' AND constraint_name='fk_fuel_counterparty';
SET @sql = IF(@has_counterparty_fk=0,
  'ALTER TABLE fuel_purchases ADD CONSTRAINT fk_fuel_counterparty FOREIGN KEY (counterparty_id) REFERENCES counterparties(id)',
  'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
