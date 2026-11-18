CREATE TABLE IF NOT EXISTS income_sources (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 provider VARCHAR(60) NOT NULL,
 name VARCHAR(160) NOT NULL,
 url VARCHAR(500) NOT NULL DEFAULT '',
 active BOOLEAN NOT NULL DEFAULT TRUE,
 automatic_sync BOOLEAN NOT NULL DEFAULT FALSE,
 import_documents BOOLEAN NOT NULL DEFAULT TRUE,
 category_id BIGINT UNSIGNED NULL,
 sync_from DATE NULL,
 last_sync_at DATETIME NULL,
 last_error VARCHAR(300) NULL,
 last_summary JSON NULL,
 UNIQUE KEY unique_provider (provider),
 FOREIGN KEY (category_id) REFERENCES categories(id)
);
CREATE TABLE IF NOT EXISTS income_source_records (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 source_id BIGINT UNSIGNED NOT NULL,
 external_id VARCHAR(190) NOT NULL,
 document_id BIGINT UNSIGNED NOT NULL,
 source_metadata JSON NULL,
 UNIQUE KEY unique_external_income (source_id,external_id),
 UNIQUE KEY unique_source_document (document_id),
 FOREIGN KEY (source_id) REFERENCES income_sources(id),
 FOREIGN KEY (document_id) REFERENCES documents(id)
);
