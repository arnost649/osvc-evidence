-- Additive only; no historical amounts or invoice values are rewritten.
ALTER TABLE payments
 ADD COLUMN invoice_amount_czk DECIMAL(14,2) NULL,
 ADD COLUMN payment_received_czk DECIMAL(14,2) NULL,
 ADD COLUMN payment_currency CHAR(3) NULL,
 ADD COLUMN fx_settlement_diff_czk DECIMAL(14,2) NULL,
 ADD COLUMN payment_needs_review BOOLEAN NOT NULL DEFAULT FALSE;
