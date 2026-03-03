-- Add submissions table for community event submissions
-- Run: psql $DATABASE_URL < scripts/migrations/add_submissions.sql

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
