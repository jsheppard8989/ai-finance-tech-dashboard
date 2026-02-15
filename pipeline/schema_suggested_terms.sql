-- Suggested Terms Management
-- Tracks user-submitted terms and auto-suggested terms from content

CREATE TABLE IF NOT EXISTS suggested_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL UNIQUE,
    definition TEXT,
    investment_implications TEXT,
    -- Source tracking
    source_type TEXT CHECK(source_type IN ('user_submission', 'auto_extracted', 'manual_add')),
    source_contact TEXT,  -- For user submissions: email or name
    source_context TEXT,  -- Where was this term found (podcast/episode or newsletter)
    
    -- Priority scoring
    mention_count INTEGER DEFAULT 1,
    source_diversity INTEGER DEFAULT 1,  -- Number of unique sources mentioning
    relevance_score INTEGER DEFAULT 0,   -- 0-100 calculated score
    last_mentioned_date DATE,
    
    -- Status workflow
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'under_review', 'approved', 'rejected', 'duplicate')),
    reviewed_by TEXT,  -- Who reviewed it
    reviewed_at TIMESTAMP,
    review_notes TEXT,
    
    -- Voting (for user-submitted terms)
    vote_count INTEGER DEFAULT 0,
    
    -- Timestamps
    submitted_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for efficient queries
CREATE INDEX IF NOT EXISTS idx_suggested_status ON suggested_terms(status);
CREATE INDEX IF NOT EXISTS idx_suggested_score ON suggested_terms(relevance_score DESC);
CREATE INDEX IF NOT EXISTS idx_suggested_mentions ON suggested_terms(mention_count DESC);

-- View for pending terms sorted by priority
CREATE VIEW IF NOT EXISTS v_priority_suggestions AS
SELECT 
    id,
    term,
    definition,
    investment_implications,
    source_type,
    mention_count,
    source_diversity,
    relevance_score,
    submitted_date,
    -- Calculate priority score: mention_weight * 10 + diversity * 20 + base_score
    (mention_count * 10 + source_diversity * 20 + relevance_score) as priority_score
FROM suggested_terms
WHERE status = 'pending'
ORDER BY priority_score DESC, submitted_date ASC;

-- Trigger to update timestamp
CREATE TRIGGER IF NOT EXISTS update_suggested_terms_timestamp 
AFTER UPDATE ON suggested_terms
BEGIN
    UPDATE suggested_terms SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;