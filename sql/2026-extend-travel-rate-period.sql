-- The original seed rate was accidentally limited to the first trip date.
-- This migration is deliberately exact and idempotent: it only expands that
-- 2026 Natural 95 passenger-car rate, without changing its monetary values.
UPDATE travel_rates
SET valid_from = '2026-01-01', valid_to = '2026-12-31'
WHERE id = 1
  AND vehicle_type = 'passenger_car'
  AND fuel_type = 'Natural 95'
  AND base_rate_per_km = 5.900
  AND average_fuel_price_per_liter = 34.700
  AND valid_from = '2026-09-12'
  AND valid_to = '2026-09-12';
