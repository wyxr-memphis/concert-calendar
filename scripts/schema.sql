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
  is_wyxr_presents BOOLEAN DEFAULT false,
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

-- Community event submissions
CREATE TABLE IF NOT EXISTS submissions (
  id SERIAL PRIMARY KEY,
  artist_name VARCHAR(200) NOT NULL,
  venue VARCHAR(200) NOT NULL,
  event_date DATE NOT NULL,
  event_time TIME,
  description TEXT,
  submitter_name VARCHAR(100) NOT NULL,
  submitter_email VARCHAR(254) NOT NULL,
  status VARCHAR(20) DEFAULT 'pending',
  submitted_at TIMESTAMP DEFAULT NOW(),
  reviewed_at TIMESTAMP,
  reviewed_by VARCHAR(100),
  created_event_id VARCHAR(255),
  honeypot VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status);
CREATE INDEX IF NOT EXISTS idx_submissions_date ON submissions(submitted_at DESC);

-- Dismissed venue names (unmapped venue names that are not real venues)
-- A dismissed name re-appears automatically if new events are imported after the dismissal date
CREATE TABLE IF NOT EXISTS dismissed_venue_names (
    name TEXT PRIMARY KEY,
    dismissed_at TIMESTAMPTZ DEFAULT NOW()
);

-- Sponsor callouts (promotional graphics shown inline in the calendar and RSS feed)
CREATE TABLE IF NOT EXISTS sponsors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  image_url TEXT NOT NULL,
  link_url TEXT,
  display_after_date DATE NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sponsors_dates ON sponsors (start_date, end_date) WHERE is_active = true;

-- Calendar sponsor (single featured sponsor shown above the event list)
CREATE TABLE IF NOT EXISTS calendar_sponsor (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  image_url   TEXT NOT NULL,
  link_url    TEXT,
  copy_line   TEXT,
  start_date  DATE NOT NULL,
  end_date    DATE NOT NULL,
  is_active   BOOLEAN DEFAULT true,
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  updated_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cal_sponsor_dates
  ON calendar_sponsor (start_date, end_date) WHERE is_active = true;

-- Public API keys (honor system — no hard rate limiting)
CREATE TABLE IF NOT EXISTS api_keys (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  key         TEXT UNIQUE NOT NULL,
  name        TEXT NOT NULL,
  email       TEXT,
  notes       TEXT,
  is_active   BOOLEAN DEFAULT TRUE,
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  last_used_at TIMESTAMPTZ
);

-- Per-key request log for usage analytics
CREATE TABLE IF NOT EXISTS api_request_logs (
  id          BIGSERIAL PRIMARY KEY,
  api_key_id  UUID REFERENCES api_keys(id),
  key_prefix  TEXT,
  endpoint    TEXT,
  query_params TEXT,
  ip          TEXT,
  status_code INTEGER,
  duration_ms INTEGER,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_request_logs_key ON api_request_logs(api_key_id);
CREATE INDEX IF NOT EXISTS idx_request_logs_created ON api_request_logs(created_at);

-- Public API key requests (pending admin approval before a key is issued)
CREATE TABLE IF NOT EXISTS api_key_requests (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name         TEXT NOT NULL,
  email        TEXT NOT NULL,
  company      TEXT,
  use_case     TEXT,
  status       TEXT DEFAULT 'pending',
  submitted_at TIMESTAMPTZ DEFAULT NOW(),
  reviewed_at  TIMESTAMPTZ,
  api_key_id   UUID REFERENCES api_keys(id)
);
CREATE INDEX IF NOT EXISTS idx_api_key_requests_status ON api_key_requests(status);
