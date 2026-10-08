-- Two-pass analyzer schema additions (safe migration for existing DB)
-- Adds columns to store extraction JSON and REAL ALPHA brief alongside episode

-- Add nullable columns to podcast_episodes for two-pass artifacts
ALTER TABLE podcast_episodes ADD COLUMN extraction_json TEXT;
ALTER TABLE podcast_episodes ADD COLUMN brief_markdown TEXT;
ALTER TABLE podcast_episodes ADD COLUMN analyzer_mode TEXT DEFAULT 'legacy';
ALTER TABLE podcast_episodes ADD COLUMN analysis_cost_usd REAL;

-- Cache table for two-pass extractions (keyed by episode_id + transcript hash)
CREATE TABLE IF NOT EXISTS two_pass_cache (
    episode_id INTEGER NOT NULL,
    transcript_sha256 TEXT NOT NULL,
    extraction_json TEXT,
    brief_markdown TEXT,
    pass1_input_tokens INTEGER,
    pass1_output_tokens INTEGER,
    pass2_input_tokens INTEGER,
    pass2_output_tokens INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (episode_id, transcript_sha256)
);

-- Index for cache lookups
CREATE INDEX IF NOT EXISTS idx_two_pass_cache_episode ON two_pass_cache(episode_id);
