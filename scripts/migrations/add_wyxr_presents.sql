-- Add is_wyxr_presents column to events table
-- Run: psql $DATABASE_URL < scripts/migrations/add_wyxr_presents.sql

ALTER TABLE events ADD COLUMN IF NOT EXISTS is_wyxr_presents BOOLEAN DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_events_wyxr_presents ON events(is_wyxr_presents) WHERE is_wyxr_presents = true;

-- Mark initial WYXR Presents events
UPDATE events SET is_wyxr_presents = true WHERE id = 'de0b7981-7217-4f1e-90d0-041e7914c94d';  -- Pull Up 3/12
UPDATE events SET is_wyxr_presents = true WHERE id = 'a5f0fd76-2b50-4114-a0d4-1485a724634b';  -- Stereo Session 4/8
