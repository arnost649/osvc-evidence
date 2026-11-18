-- Additive migration. Existing categories and confirmed tax snapshots remain intact.
CREATE TABLE system_types (
 type_key VARCHAR(40) NOT NULL PRIMARY KEY,
 display_label VARCHAR(100) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT INTO system_types VALUES ('income','Příjem'),('expense','Nákup'),('trip','Doprava'),('fuel','PHM'),('income_connector','Externí příjem'),('system_adjustment','Korekce');
ALTER TABLE payments ADD COLUMN system_type VARCHAR(40) NULL DEFAULT NULL;
UPDATE payments p LEFT JOIN income_source_records r ON r.document_id=p.document_id
 SET p.updated_at=p.updated_at,p.system_type=CASE WHEN p.fuel_purchase_id IS NOT NULL THEN 'fuel' WHEN p.direction='income' AND r.id IS NOT NULL THEN 'income_connector' ELSE p.direction END
 WHERE p.system_type IS NULL;
