-- Memphis Concert Calendar — Database Schema
-- PostgreSQL on Render
--
-- Usage:
--   psql $DATABASE_URL < scripts/schema.sql

-- Events table
CREATE TABLE IF NOT EXISTS events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  venue TEXT,
  date DATE NOT NULL,
  start_time TEXT,
  doors_time TEXT,
  ticket_url TEXT,
  ticket_price TEXT,
  image_url TEXT,
  description TEXT,
  genre TEXT,
  source TEXT DEFAULT 'manual',
  is_featured BOOLEAN DEFAULT false,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);
CREATE INDEX IF NOT EXISTS idx_events_featured ON events(is_featured) WHERE is_featured = true;

-- Scraper log table
CREATE TABLE IF NOT EXISTS scrape_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scraper_name TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'running',
  events_found INTEGER DEFAULT 0,
  events_added INTEGER DEFAULT 0,
  events_updated INTEGER DEFAULT 0,
  events_skipped INTEGER DEFAULT 0,
  error_message TEXT,
  details JSONB
);

CREATE INDEX IF NOT EXISTS idx_scrape_logs_started ON scrape_logs(started_at DESC);
