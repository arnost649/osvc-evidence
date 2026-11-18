-- Existing numeric field remains the effective ratio snapshot. No row reclassification.
ALTER TABLE payments ADD COLUMN tax_mode ENUM('category','100','0','custom') NULL DEFAULT NULL;
