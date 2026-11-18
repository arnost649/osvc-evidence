ALTER TABLE categories
 ADD COLUMN tax_default_mode ENUM('ratio','custom_required','individual') NOT NULL DEFAULT 'individual',
 ADD COLUMN available_for_manual_expense BOOLEAN NOT NULL DEFAULT TRUE;
UPDATE categories SET tax_default_mode='ratio' WHERE tax_deductible_pct IS NOT NULL;
-- Preserve already effective legacy decisions before removing dynamic inheritance.
UPDATE payments p JOIN categories c ON c.id=p.category_id
 SET p.tax_mode='category',p.tax_deductible_pct=c.tax_deductible_pct
 WHERE p.direction='expense' AND p.fuel_purchase_id IS NULL
 AND p.tax_deductible_pct IS NULL AND c.tax_deductible_pct BETWEEN 0 AND 100;
UPDATE categories SET available_for_manual_expense=FALSE WHERE name='PHM';
-- Příklad výchozích daňových režimů kategorií – upravte podle své instalace a odkomentujte:
-- UPDATE categories SET tax_default_mode='ratio',tax_deductible_pct=100
--  WHERE type IN ('expense','both') AND name IN ('Kancelářské potřeby','Software');
-- UPDATE categories SET tax_default_mode='custom_required',tax_deductible_pct=NULL
--  WHERE type IN ('expense','both') AND name='Telefon';
