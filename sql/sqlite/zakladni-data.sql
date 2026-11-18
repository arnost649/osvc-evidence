-- OSVČ – výchozí data nové (samostatné) instalace SQLite. Spouští sqlite_db.zaloz(..., zakladni_data=True) po schema.sql.
-- Desetinná čísla jako celá (DEC3 = tisíciny): 5,900 Kč/km → 5900, 34,700 Kč/l → 34700.
-- Názvy typů záznamů (výchozí názvy z osvc_app/system_types.py; mění se v Nastavení → Názvy typů).
INSERT INTO system_types (type_key, display_label) VALUES
  ('income','Ruční příjem'),('expense','Nákup'),('trip','Doprava'),('fuel','PHM'),('income_connector','Příjem z e-shopu'),('system_adjustment','Korekce');
-- Vyhláškové sazby pro náhrady za jízdy (z migrace alter-trip-travel-cost.sql; další roky a paliva doplní aktualizace aplikace).
INSERT INTO travel_rates (valid_from, valid_to, vehicle_type, fuel_type, base_rate_per_km, average_fuel_price_per_liter) VALUES
  ('2026-01-01', '2026-12-31', 'passenger_car', 'Natural 95', 5900, 34700);
