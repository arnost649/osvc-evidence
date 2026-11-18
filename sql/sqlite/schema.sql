-- OSVČ – struktura databáze SQLite, verze 1. Vygenerováno ze struktury MySQL (stav po všech migracích v sql/).
-- Desetinná čísla jako celá: DECs = hodnota × 10^s (DEC2 = haléře). Text porovnává OSVC_CI (bez ohledu na velikost písmen
-- a diakritiku, jako MySQL utf8mb4_0900_ai_ci) – databázi otevírat přes osvc_app (registruje porovnání a převody).
PRAGMA user_version = 1;

CREATE TABLE annual_closures (
  tax_year INTEGER NOT NULL,
  ruleset_id TEXT COLLATE OSVC_CI NOT NULL,
  ruleset TEXT CHECK (ruleset IS NULL OR json_valid(ruleset)) NOT NULL,
  snapshot TEXT CHECK (snapshot IS NULL OR json_valid(snapshot)) NOT NULL,
  pdf_attachment_id INTEGER,
  closed_at DATETIME,
  PRIMARY KEY (tax_year)
);

CREATE TABLE app_accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT COLLATE OSVC_CI NOT NULL,
  password_hash TEXT COLLATE OSVC_CI NOT NULL,
  verification_email TEXT COLLATE OSVC_CI,
  email_verified_at DATETIME,
  pending_email TEXT COLLATE OSVC_CI,
  email_verification_token_hash TEXT COLLATE OSVC_CI,
  email_verification_expires_at DATETIME,
  password_reset_token_hash TEXT COLLATE OSVC_CI,
  password_reset_expires_at DATETIME,
  password_reset_requested_at DATETIME,
  password_changed_at DATETIME,
  auth_version INTEGER NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT app_accounts_uq_app_accounts_username UNIQUE (username),
  CONSTRAINT app_accounts_uq_app_accounts_verification_email UNIQUE (verification_email)
);

CREATE TABLE attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER NOT NULL,
  original_filename TEXT COLLATE OSVC_CI NOT NULL,
  stored_filename TEXT COLLATE OSVC_CI NOT NULL,
  mime_type TEXT COLLATE OSVC_CI,
  sha256 TEXT COLLATE OSVC_CI,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP,
  CONSTRAINT fk_attachment_document FOREIGN KEY (document_id) REFERENCES documents (id)
);
CREATE INDEX attachments_idx_attachment_document ON attachments (document_id);

CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type TEXT COLLATE OSVC_CI NOT NULL,
  entity_id INTEGER NOT NULL,
  action TEXT COLLATE OSVC_CI CHECK (action IN ('insert','update','cancel','restore')) NOT NULL,
  old_data TEXT CHECK (old_data IS NULL OR json_valid(old_data)),
  new_data TEXT CHECK (new_data IS NULL OR json_valid(new_data)),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX audit_log_idx_audit_created ON audit_log (created_at);
CREATE INDEX audit_log_idx_audit_entity ON audit_log (entity_type, entity_id);

CREATE TABLE bank_transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  external_id TEXT COLLATE OSVC_CI,
  booking_date DATE NOT NULL,
  amount DEC2 NOT NULL,
  currency TEXT COLLATE OSVC_CI NOT NULL DEFAULT 'CZK',
  counterparty_name TEXT COLLATE OSVC_CI,
  counter_account TEXT COLLATE OSVC_CI,
  variable_symbol TEXT COLLATE OSVC_CI,
  constant_symbol TEXT COLLATE OSVC_CI,
  specific_symbol TEXT COLLATE OSVC_CI,
  message TEXT COLLATE OSVC_CI,
  source TEXT COLLATE OSVC_CI CHECK (source IN ('manual','fio','import')) NOT NULL DEFAULT 'manual',
  raw_data TEXT CHECK (raw_data IS NULL OR json_valid(raw_data)),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP,
  CONSTRAINT bank_transactions_uq_bank_external UNIQUE (source, external_id)
);
CREATE INDEX bank_transactions_idx_bank_date ON bank_transactions (booking_date);
CREATE INDEX bank_transactions_idx_bank_vs ON bank_transactions (variable_symbol);

CREATE TABLE business_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_date DATE NOT NULL,
  name TEXT COLLATE OSVC_CI NOT NULL,
  location TEXT COLLATE OSVC_CI,
  note TEXT COLLATE OSVC_CI,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP
);
CREATE INDEX business_events_idx_business_event_date ON business_events (event_date);

CREATE TABLE categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT COLLATE OSVC_CI NOT NULL,
  type TEXT COLLATE OSVC_CI CHECK (type IN ('income','expense','both')) NOT NULL,
  tax_deductible_pct DEC2,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP,
  tax_default_mode TEXT COLLATE OSVC_CI CHECK (tax_default_mode IN ('ratio','custom_required','individual')) NOT NULL DEFAULT 'individual',
  available_for_manual_expense INTEGER NOT NULL DEFAULT 1,
  CONSTRAINT categories_uq_category_name_type UNIQUE (name, type)
);

CREATE TABLE counterparties (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT COLLATE OSVC_CI NOT NULL,
  operator_name TEXT COLLATE OSVC_CI,
  source TEXT COLLATE OSVC_CI CHECK (source IN ('manual','woocommerce')) NOT NULL DEFAULT 'manual',
  role TEXT COLLATE OSVC_CI CHECK (role IN ('supplier','customer','both','fuel_station')) NOT NULL DEFAULT 'customer',
  ico TEXT COLLATE OSVC_CI,
  dic TEXT COLLATE OSVC_CI,
  street TEXT COLLATE OSVC_CI,
  city TEXT COLLATE OSVC_CI,
  postal_code TEXT COLLATE OSVC_CI,
  official_address TEXT COLLATE OSVC_CI,
  country_code TEXT COLLATE OSVC_CI NOT NULL DEFAULT 'CZ',
  email TEXT COLLATE OSVC_CI,
  phone TEXT COLLATE OSVC_CI,
  note TEXT COLLATE OSVC_CI,
  verified_at DATETIME,
  verification_source TEXT COLLATE OSVC_CI,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP
);
CREATE INDEX counterparties_idx_counterparty_address_book ON counterparties (source, role, name);
CREATE INDEX counterparties_idx_counterparty_ico ON counterparties (ico);
CREATE INDEX counterparties_idx_counterparty_name ON counterparties (name);

CREATE TABLE document_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER NOT NULL,
  category_id INTEGER,
  description TEXT COLLATE OSVC_CI NOT NULL,
  quantity DEC3 NOT NULL DEFAULT 1000,
  unit TEXT COLLATE OSVC_CI,
  unit_price DEC4,
  net_amount DEC2,
  vat_rate DEC2,
  vat_amount DEC2,
  gross_amount DEC2 NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP,
  CONSTRAINT fk_items_category FOREIGN KEY (category_id) REFERENCES categories (id),
  CONSTRAINT fk_items_document FOREIGN KEY (document_id) REFERENCES documents (id)
);
CREATE INDEX document_items_idx_items_category ON document_items (category_id);
CREATE INDEX document_items_idx_items_document ON document_items (document_id);

CREATE TABLE documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_type TEXT COLLATE OSVC_CI CHECK (document_type IN ('issued_invoice','received_invoice','receipt','credit_note','other')) NOT NULL,
  number TEXT COLLATE OSVC_CI,
  variable_symbol TEXT COLLATE OSVC_CI,
  counterparty_id INTEGER,
  issue_date DATE NOT NULL,
  taxable_date DATE,
  due_date DATE,
  currency TEXT COLLATE OSVC_CI NOT NULL DEFAULT 'CZK',
  net_total DEC2,
  vat_total DEC2,
  gross_total DEC2 NOT NULL,
  source TEXT COLLATE OSVC_CI CHECK (source IN ('manual','woocommerce','fio','import','other')) NOT NULL DEFAULT 'manual',
  source_ref TEXT COLLATE OSVC_CI,
  note TEXT COLLATE OSVC_CI,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP,
  CONSTRAINT fk_documents_counterparty FOREIGN KEY (counterparty_id) REFERENCES counterparties (id)
);
CREATE INDEX documents_fk_documents_counterparty ON documents (counterparty_id);
CREATE INDEX documents_idx_document_issue_date ON documents (issue_date);
CREATE INDEX documents_idx_document_number ON documents (number);
CREATE INDEX documents_idx_document_source_ref ON documents (source, source_ref);
CREATE INDEX documents_idx_document_vs ON documents (variable_symbol);

CREATE TABLE fuel_purchases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vehicle_id INTEGER NOT NULL,
  counterparty_id INTEGER,
  event_id INTEGER,
  document_id INTEGER,
  purchase_date DATE NOT NULL,
  liters DEC3 NOT NULL,
  price_per_liter DEC3 NOT NULL,
  total_amount DEC2 NOT NULL,
  odometer_km INTEGER,
  station TEXT COLLATE OSVC_CI,
  station_name TEXT COLLATE OSVC_CI,
  note TEXT COLLATE OSVC_CI,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP,
  CONSTRAINT fk_fuel_counterparty FOREIGN KEY (counterparty_id) REFERENCES counterparties (id),
  CONSTRAINT fk_fuel_document FOREIGN KEY (document_id) REFERENCES documents (id),
  CONSTRAINT fk_fuel_event FOREIGN KEY (event_id) REFERENCES business_events (id),
  CONSTRAINT fk_fuel_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicles (id)
);
CREATE INDEX fuel_purchases_fk_fuel_document ON fuel_purchases (document_id);
CREATE INDEX fuel_purchases_idx_fuel_counterparty ON fuel_purchases (counterparty_id);
CREATE INDEX fuel_purchases_idx_fuel_date ON fuel_purchases (purchase_date);
CREATE INDEX fuel_purchases_idx_fuel_event ON fuel_purchases (event_id);
CREATE INDEX fuel_purchases_idx_fuel_vehicle ON fuel_purchases (vehicle_id);

CREATE TABLE income_source_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER NOT NULL,
  external_id TEXT COLLATE OSVC_CI NOT NULL,
  document_id INTEGER NOT NULL,
  source_metadata TEXT CHECK (source_metadata IS NULL OR json_valid(source_metadata)),
  CONSTRAINT income_source_records_unique_external_income UNIQUE (source_id, external_id),
  CONSTRAINT income_source_records_unique_source_document UNIQUE (document_id),
  CONSTRAINT income_source_records_ibfk_1 FOREIGN KEY (source_id) REFERENCES income_sources (id),
  CONSTRAINT income_source_records_ibfk_2 FOREIGN KEY (document_id) REFERENCES documents (id)
);

CREATE TABLE income_sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT COLLATE OSVC_CI NOT NULL,
  name TEXT COLLATE OSVC_CI NOT NULL,
  url TEXT COLLATE OSVC_CI NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1,
  automatic_sync INTEGER NOT NULL DEFAULT 0,
  import_documents INTEGER NOT NULL DEFAULT 1,
  category_id INTEGER,
  sync_from DATE,
  last_sync_at DATETIME,
  last_error TEXT COLLATE OSVC_CI,
  last_summary TEXT CHECK (last_summary IS NULL OR json_valid(last_summary)),
  configuration TEXT CHECK (configuration IS NULL OR json_valid(configuration)),
  secret_profile TEXT COLLATE OSVC_CI,
  sync_state TEXT CHECK (sync_state IS NULL OR json_valid(sync_state)),
  diagnostics TEXT CHECK (diagnostics IS NULL OR json_valid(diagnostics)),
  CONSTRAINT income_sources_ibfk_1 FOREIGN KEY (category_id) REFERENCES categories (id)
);
CREATE INDEX income_sources_category_id ON income_sources (category_id);

CREATE TABLE osvc_profile (
  id INTEGER NOT NULL,
  data TEXT CHECK (data IS NULL OR json_valid(data)) NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
);

CREATE TABLE osvc_year_profiles (
  tax_year INTEGER NOT NULL,
  data TEXT CHECK (data IS NULL OR json_valid(data)) NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (tax_year)
);

CREATE TABLE payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER,
  event_id INTEGER,
  fuel_purchase_id INTEGER,
  bank_transaction_id INTEGER,
  counterparty_id INTEGER,
  category_id INTEGER,
  description TEXT COLLATE OSVC_CI,
  payment_date DATE NOT NULL,
  direction TEXT COLLATE OSVC_CI CHECK (direction IN ('income','expense')) NOT NULL,
  method TEXT COLLATE OSVC_CI CHECK (method IN ('bank','cash','card','other')),
  amount DEC2 NOT NULL,
  currency TEXT COLLATE OSVC_CI NOT NULL DEFAULT 'CZK',
  note TEXT COLLATE OSVC_CI,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP,
  tax_deductible_pct DEC2,
  tax_mode TEXT COLLATE OSVC_CI CHECK (tax_mode IN ('category','100','0','custom')),
  system_type TEXT COLLATE OSVC_CI,
  invoice_amount_czk DEC2,
  payment_received_czk DEC2,
  payment_currency TEXT COLLATE OSVC_CI,
  fx_settlement_diff_czk DEC2,
  payment_needs_review INTEGER NOT NULL DEFAULT 0,
  CONSTRAINT chk_payment_tax_pct CHECK (tax_deductible_pct IS NULL OR tax_deductible_pct BETWEEN 0 AND 10000),
  CONSTRAINT fk_payment_bank FOREIGN KEY (bank_transaction_id) REFERENCES bank_transactions (id),
  CONSTRAINT fk_payment_category FOREIGN KEY (category_id) REFERENCES categories (id),
  CONSTRAINT fk_payment_counterparty FOREIGN KEY (counterparty_id) REFERENCES counterparties (id),
  CONSTRAINT fk_payment_document FOREIGN KEY (document_id) REFERENCES documents (id),
  CONSTRAINT fk_payment_event FOREIGN KEY (event_id) REFERENCES business_events (id),
  CONSTRAINT fk_payment_fuel_purchase FOREIGN KEY (fuel_purchase_id) REFERENCES fuel_purchases (id)
);
CREATE INDEX payments_fk_payment_bank ON payments (bank_transaction_id);
CREATE INDEX payments_idx_payment_category ON payments (category_id);
CREATE INDEX payments_idx_payment_counterparty ON payments (counterparty_id);
CREATE INDEX payments_idx_payment_date ON payments (payment_date);
CREATE INDEX payments_idx_payment_document ON payments (document_id);
CREATE INDEX payments_idx_payment_event ON payments (event_id);
CREATE INDEX payments_idx_payment_fuel_purchase ON payments (fuel_purchase_id);

CREATE TABLE system_types (
  type_key TEXT COLLATE OSVC_CI NOT NULL,
  display_label TEXT COLLATE OSVC_CI NOT NULL,
  PRIMARY KEY (type_key)
);

CREATE TABLE travel_rates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  valid_from DATE NOT NULL,
  valid_to DATE NOT NULL,
  vehicle_type TEXT COLLATE OSVC_CI NOT NULL,
  fuel_type TEXT COLLATE OSVC_CI NOT NULL,
  base_rate_per_km DEC3 NOT NULL,
  average_fuel_price_per_liter DEC3 NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP,
  CONSTRAINT travel_rates_uq_travel_rate_period UNIQUE (valid_from, valid_to, vehicle_type, fuel_type)
);
CREATE INDEX travel_rates_idx_travel_rate_lookup ON travel_rates (vehicle_type, fuel_type, valid_from, valid_to);

CREATE TABLE trips (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vehicle_id INTEGER NOT NULL,
  event_id INTEGER,
  fuel_purchase_id INTEGER,
  fuel_price_source TEXT COLLATE OSVC_CI,
  travel_rate_id INTEGER,
  trip_date DATE NOT NULL,
  trip_end_date DATE NOT NULL,
  origin TEXT COLLATE OSVC_CI NOT NULL,
  destination TEXT COLLATE OSVC_CI NOT NULL,
  purpose TEXT COLLATE OSVC_CI NOT NULL,
  odometer_start INTEGER,
  odometer_end INTEGER,
  distance_km DEC1 NOT NULL,
  calculation_consumption_l_100km DEC3,
  calculation_base_rate_per_km DEC3,
  calculation_fuel_price_per_liter DEC3,
  base_compensation DEC2,
  fuel_compensation DEC2,
  travel_cost_total DEC2,
  note TEXT COLLATE OSVC_CI,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP,
  CONSTRAINT fk_trip_event FOREIGN KEY (event_id) REFERENCES business_events (id),
  CONSTRAINT fk_trip_fuel_purchase FOREIGN KEY (fuel_purchase_id) REFERENCES fuel_purchases (id),
  CONSTRAINT fk_trip_travel_rate FOREIGN KEY (travel_rate_id) REFERENCES travel_rates (id),
  CONSTRAINT fk_trip_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicles (id)
);
CREATE INDEX trips_idx_trip_date ON trips (trip_date);
CREATE INDEX trips_idx_trip_end_date ON trips (trip_end_date);
CREATE INDEX trips_idx_trip_event ON trips (event_id);
CREATE INDEX trips_idx_trip_fuel_purchase ON trips (fuel_purchase_id);
CREATE INDEX trips_idx_trip_travel_rate ON trips (travel_rate_id);
CREATE INDEX trips_idx_trip_vehicle ON trips (vehicle_id);

CREATE TABLE vehicles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT COLLATE OSVC_CI NOT NULL,
  registration_plate TEXT COLLATE OSVC_CI,
  fuel_type TEXT COLLATE OSVC_CI,
  normalized_consumption_l_100km DEC3,
  note TEXT COLLATE OSVC_CI,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP
);

CREATE TRIGGER app_accounts_updated_at_aktualizace AFTER UPDATE ON app_accounts FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE app_accounts SET updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id; END;
CREATE TRIGGER bank_transactions_updated_at_aktualizace AFTER UPDATE ON bank_transactions FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE bank_transactions SET updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id; END;
CREATE TRIGGER business_events_updated_at_aktualizace AFTER UPDATE ON business_events FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE business_events SET updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id; END;
CREATE TRIGGER categories_updated_at_aktualizace AFTER UPDATE ON categories FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE categories SET updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id; END;
CREATE TRIGGER counterparties_updated_at_aktualizace AFTER UPDATE ON counterparties FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE counterparties SET updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id; END;
CREATE TRIGGER document_items_updated_at_aktualizace AFTER UPDATE ON document_items FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE document_items SET updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id; END;
CREATE TRIGGER documents_updated_at_aktualizace AFTER UPDATE ON documents FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE documents SET updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id; END;
CREATE TRIGGER fuel_purchases_updated_at_aktualizace AFTER UPDATE ON fuel_purchases FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE fuel_purchases SET updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id; END;
CREATE TRIGGER osvc_profile_updated_at_aktualizace AFTER UPDATE ON osvc_profile FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE osvc_profile SET updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id; END;
CREATE TRIGGER osvc_year_profiles_updated_at_aktualizace AFTER UPDATE ON osvc_year_profiles FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE osvc_year_profiles SET updated_at=CURRENT_TIMESTAMP WHERE tax_year=NEW.tax_year; END;
CREATE TRIGGER payments_updated_at_aktualizace AFTER UPDATE ON payments FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE payments SET updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id; END;
CREATE TRIGGER travel_rates_updated_at_aktualizace AFTER UPDATE ON travel_rates FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE travel_rates SET updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id; END;
CREATE TRIGGER trips_updated_at_aktualizace AFTER UPDATE ON trips FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE trips SET updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id; END;
CREATE TRIGGER vehicles_updated_at_aktualizace AFTER UPDATE ON vehicles FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE vehicles SET updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id; END;
