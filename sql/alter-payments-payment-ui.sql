ALTER TABLE payments
  ADD COLUMN counterparty_id BIGINT UNSIGNED NULL AFTER document_id,
  ADD COLUMN category_id BIGINT UNSIGNED NULL AFTER counterparty_id,
  ADD COLUMN description VARCHAR(255) NULL AFTER amount,
  ADD CONSTRAINT fk_payment_counterparty FOREIGN KEY (counterparty_id) REFERENCES counterparties(id),
  ADD CONSTRAINT fk_payment_category FOREIGN KEY (category_id) REFERENCES categories(id);
