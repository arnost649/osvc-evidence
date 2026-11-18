-- Jednorázově spusťte jako správce MySQL nad databází osvc.
ALTER TABLE vehicles
  ADD COLUMN normalized_consumption_l_100km DECIMAL(6,3) NULL AFTER fuel_type;

CREATE TABLE travel_rates (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  valid_from DATE NOT NULL,
  valid_to DATE NOT NULL,
  vehicle_type VARCHAR(30) NOT NULL,
  fuel_type VARCHAR(30) NOT NULL,
  base_rate_per_km DECIMAL(10,3) NOT NULL,
  average_fuel_price_per_liter DECIMAL(10,3) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP NULL DEFAULT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_travel_rate_period (valid_from, valid_to, vehicle_type, fuel_type),
  KEY idx_travel_rate_lookup (vehicle_type, fuel_type, valid_from, valid_to)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO travel_rates
  (valid_from, valid_to, vehicle_type, fuel_type, base_rate_per_km, average_fuel_price_per_liter)
VALUES
  ('2026-01-01', '2026-12-31', 'passenger_car', 'Natural 95', 5.900, 34.700);

ALTER TABLE trips
  ADD COLUMN fuel_purchase_id BIGINT UNSIGNED NULL AFTER event_id,
  ADD COLUMN travel_rate_id BIGINT UNSIGNED NULL AFTER fuel_purchase_id,
  ADD COLUMN calculation_consumption_l_100km DECIMAL(6,3) NULL AFTER distance_km,
  ADD COLUMN calculation_base_rate_per_km DECIMAL(10,3) NULL AFTER calculation_consumption_l_100km,
  ADD COLUMN calculation_fuel_price_per_liter DECIMAL(10,3) NULL AFTER calculation_base_rate_per_km,
  ADD COLUMN base_compensation DECIMAL(14,2) NULL AFTER calculation_fuel_price_per_liter,
  ADD COLUMN fuel_compensation DECIMAL(14,2) NULL AFTER base_compensation,
  ADD COLUMN travel_cost_total DECIMAL(14,2) NULL AFTER fuel_compensation,
  ADD KEY idx_trip_fuel_purchase (fuel_purchase_id),
  ADD KEY idx_trip_travel_rate (travel_rate_id),
  ADD CONSTRAINT fk_trip_fuel_purchase FOREIGN KEY (fuel_purchase_id) REFERENCES fuel_purchases (id),
  ADD CONSTRAINT fk_trip_travel_rate FOREIGN KEY (travel_rate_id) REFERENCES travel_rates (id);
