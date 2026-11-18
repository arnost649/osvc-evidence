ALTER TABLE income_sources DROP INDEX unique_provider,
 ADD configuration JSON NULL,
 ADD secret_profile VARCHAR(80) NULL,
 ADD sync_state JSON NULL,
 ADD diagnostics JSON NULL;
