-- Idempotent snapshot marker for the two canonical PHM price modes.
SET @has_fuel_price_source := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'trips' AND column_name = 'fuel_price_source'
);
SET @fuel_price_source_sql := IF(@has_fuel_price_source = 0,
  'ALTER TABLE trips ADD COLUMN fuel_price_source VARCHAR(16) NULL AFTER fuel_purchase_id',
  'SELECT 1');
PREPARE fuel_price_source_stmt FROM @fuel_price_source_sql;
EXECUTE fuel_price_source_stmt;
DEALLOCATE PREPARE fuel_price_source_stmt;

UPDATE trips
SET fuel_price_source = CASE WHEN fuel_purchase_id IS NULL THEN 'statutory' ELSE 'receipt' END
WHERE deleted_at IS NULL AND fuel_price_source IS NULL;
