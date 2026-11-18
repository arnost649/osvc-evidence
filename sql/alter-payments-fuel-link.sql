ALTER TABLE payments
  ADD COLUMN fuel_purchase_id BIGINT UNSIGNED NULL AFTER document_id,
  ADD KEY idx_payment_fuel_purchase (fuel_purchase_id),
  ADD CONSTRAINT fk_payment_fuel_purchase FOREIGN KEY (fuel_purchase_id) REFERENCES fuel_purchases(id);
