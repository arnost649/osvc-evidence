ALTER TABLE trips
  ADD COLUMN trip_end_date DATE NULL AFTER trip_date,
  ADD KEY idx_trip_end_date (trip_end_date);

UPDATE trips
SET trip_end_date = trip_date
WHERE trip_end_date IS NULL;

ALTER TABLE trips
  MODIFY COLUMN trip_end_date DATE NOT NULL;
