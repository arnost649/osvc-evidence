CREATE TABLE business_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_date DATE NOT NULL,
  name VARCHAR(200) NOT NULL,
  location VARCHAR(200) NULL,
  note TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP NULL DEFAULT NULL,
  PRIMARY KEY (id),
  KEY idx_business_event_date (event_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

ALTER TABLE trips
  ADD COLUMN event_id BIGINT UNSIGNED NULL AFTER vehicle_id,
  ADD KEY idx_trip_event (event_id),
  ADD CONSTRAINT fk_trip_event FOREIGN KEY (event_id) REFERENCES business_events(id);

ALTER TABLE fuel_purchases
  ADD COLUMN event_id BIGINT UNSIGNED NULL AFTER vehicle_id,
  ADD KEY idx_fuel_event (event_id),
  ADD CONSTRAINT fk_fuel_event FOREIGN KEY (event_id) REFERENCES business_events(id);

ALTER TABLE payments
  ADD COLUMN event_id BIGINT UNSIGNED NULL AFTER document_id,
  ADD KEY idx_payment_event (event_id),
  ADD CONSTRAINT fk_payment_event FOREIGN KEY (event_id) REFERENCES business_events(id);
