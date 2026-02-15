-- Database Schema for AI Finance Tech Dashboard
-- SQLite - file-based, no server needed

-- Main ticker mentions table (core data)
CREATE TABLE ticker_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK(source_type IN ('podcast', 'newsletter')),
    source_name TEXT NOT NULL,
    episode_title TEXT,
    mention_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    context TEXT,  -- excerpt where ticker was mentioned
    conviction_score INTEGER CHECK(conviction_score BETWEEN -100 AND 100),
    sentiment TEXT CHECK(sentiment IN ('bullish', 'bearish', 'neutral')),
    timeframe TEXT CHECK(timeframe IN ('short_term', 'long_term', 'unspecified')),
    is_contrarian BOOLEAN DEFAULT 0,
    is_disruption_focused BOOLEAN DEFAULT 0,  -- for newsletter boost
    raw_mentions_count INTEGER DEFAULT 1,
    weighted_score REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Podcast episodes with full summaries
CREATE TABLE podcast_episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    podcast_name TEXT NOT NULL,
    episode_title TEXT NOT NULL,
    episode_date DATE,
    audio_url TEXT,
    transcript_path TEXT,
    summary TEXT,  -- full summary for modal display
    key_takeaways TEXT,  -- JSON array
    key_tickers TEXT,  -- JSON array of mentioned tickers
    investment_thesis TEXT,
    source_breakdown TEXT,  -- JSON with links, timestamps
    relevance_score INTEGER,
    is_processed BOOLEAN DEFAULT 0,
    added_to_site BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Newsletter/emails
CREATE TABLE newsletters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    received_date TIMESTAMP,
    content_preview TEXT,
    extracted_tickers TEXT,  -- JSON array
    is_processed BOOLEAN DEFAULT 0,
    disruption_keywords_found TEXT,  -- JSON array of matched keywords
    added_to_site BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Daily aggregated scores (for website display)
CREATE TABLE daily_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date DATE DEFAULT CURRENT_DATE,
    total_score REAL DEFAULT 0,
    podcast_mentions INTEGER DEFAULT 0,
    newsletter_mentions INTEGER DEFAULT 0,
    disruption_signals INTEGER DEFAULT 0,
    unique_sources INTEGER DEFAULT 0,
    top_sources TEXT,  -- JSON array
    conviction_level TEXT,
    contrarian_signal TEXT,
    hidden_plays TEXT,  -- JSON
    rank INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, date)
);

-- Overton Window terms tracking
CREATE TABLE overton_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL UNIQUE,
    description TEXT,
    first_detected_date DATE,
    last_mentioned_date DATE,
    mention_count INTEGER DEFAULT 1,
    source_podcasts TEXT,  -- JSON array
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'graduated', 'archived')),
    investment_implications TEXT,
    display_on_main BOOLEAN DEFAULT 1,  -- Show on main page?
    archived_date DATE,  -- When moved to archive
    archived_reason TEXT  -- Why it was archived
);

-- Definitions glossary
CREATE TABLE definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL UNIQUE,
    definition TEXT NOT NULL,
    investment_implications TEXT,
    added_date DATE DEFAULT CURRENT_DATE,
    vote_count INTEGER DEFAULT 0,
    display_on_main BOOLEAN DEFAULT 1,  -- Show on main page?
    archived_date DATE,
    archived_reason TEXT,
    display_order INTEGER DEFAULT 0  -- For ordering on main page
);

-- Latest Insights (curated highlights from podcasts/newsletters)
CREATE TABLE latest_insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source_type TEXT CHECK(source_type IN ('podcast', 'newsletter')),
    source_name TEXT NOT NULL,
    source_date DATE,
    summary TEXT,  -- Brief summary for card
    key_takeaway TEXT,  -- One-liner
    tickers_mentioned TEXT,  -- JSON array
    sentiment TEXT CHECK(sentiment IN ('bullish', 'bearish', 'neutral')),
    display_on_main BOOLEAN DEFAULT 1,
    display_order INTEGER DEFAULT 0,
    added_date DATE DEFAULT CURRENT_DATE,
    archived_date DATE,
    archived_reason TEXT,
    podcast_episode_id INTEGER,  -- Link to full episode
    FOREIGN KEY (podcast_episode_id) REFERENCES podcast_episodes(id)
);

-- Processing queue (for async processing)
CREATE TABLE processing_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type TEXT NOT NULL CHECK(item_type IN ('podcast', 'newsletter')),
    item_id INTEGER NOT NULL,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'processing', 'completed', 'failed')),
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_mentions_ticker ON ticker_mentions(ticker);
CREATE INDEX idx_mentions_date ON ticker_mentions(mention_date);
CREATE INDEX idx_mentions_source ON ticker_mentions(source_type, source_name);
CREATE INDEX idx_scores_date ON daily_scores(date);
CREATE INDEX idx_scores_ticker ON daily_scores(ticker);
CREATE INDEX idx_episodes_date ON podcast_episodes(episode_date);
CREATE INDEX idx_episodes_processed ON podcast_episodes(is_processed, added_to_site);

-- Views for common queries

-- Current day's top tickers (for website)
CREATE VIEW v_current_top_tickers AS
SELECT 
    ticker,
    total_score,
    podcast_mentions,
    newsletter_mentions,
    unique_sources,
    conviction_level,
    contrarian_signal,
    rank
FROM daily_scores
WHERE date = CURRENT_DATE
ORDER BY rank;

-- Podcast summary view (for modal display)
CREATE VIEW v_podcast_summaries AS
SELECT 
    id,
    podcast_name,
    episode_title,
    episode_date,
    summary,
    key_takeaways,
    investment_thesis,
    key_tickers
FROM podcast_episodes
WHERE added_to_site = 1
ORDER BY episode_date DESC;

-- Recent mentions with context
CREATE VIEW v_recent_mentions AS
SELECT 
    tm.ticker,
    tm.source_type,
    tm.source_name,
    tm.episode_title,
    tm.mention_date,
    tm.context,
    tm.conviction_score,
    tm.sentiment
FROM ticker_mentions tm
ORDER BY tm.mention_date DESC
LIMIT 100;