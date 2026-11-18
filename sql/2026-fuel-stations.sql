-- Additive migration: no contact reclassification, no fuel or trip updates.
ALTER TABLE counterparties MODIFY role ENUM('supplier','customer','both','fuel_station') NOT NULL DEFAULT 'customer';
