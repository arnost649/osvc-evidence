-- NULL inherits the category; a NULL category means pending assessment.
-- No existing amount, category or classification is changed.
ALTER TABLE payments ADD tax_deductible_pct DECIMAL(5,2) NULL DEFAULT NULL,
 ADD CONSTRAINT chk_payment_tax_pct CHECK (tax_deductible_pct IS NULL OR tax_deductible_pct BETWEEN 0 AND 100);
