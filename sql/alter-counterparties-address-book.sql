ALTER TABLE counterparties
  ADD COLUMN source ENUM('manual','woocommerce') NOT NULL DEFAULT 'manual' AFTER name,
  ADD COLUMN role ENUM('supplier','customer') NOT NULL DEFAULT 'customer' AFTER source,
  ADD KEY idx_counterparty_address_book (source, role, name);

UPDATE counterparties c
JOIN documents d ON d.counterparty_id = c.id AND d.source = 'woocommerce'
SET c.source = 'woocommerce', c.role = 'customer';

UPDATE counterparties c
JOIN payments p ON p.counterparty_id = c.id AND p.direction = 'expense'
SET c.source = 'manual', c.role = 'supplier'
WHERE c.source = 'manual';
