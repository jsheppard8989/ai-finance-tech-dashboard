# Memory Notes

## 🚨 CRITICAL WEBSITE AUDIT LESSON (2026-02-16) 🚨

**I FAILED to properly audit the website. This is UNACCEPTABLE.**

### The Mistake:
- Insights section was **completely hardcoded in HTML**
- I ran an "audit" and didn't catch this
- Only discovered it when user asked why new insights weren't appearing

### Audit Checklist (MANDATORY for all future audits):
```
□ Search for hardcoded dates: grep -E "(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+[0-9]{1,2}" index.html
□ Search for hardcoded titles: grep -E "<strong>.*:</strong>" index.html
□ Verify ALL content sections load from dashboardData
□ Check that no content is manually written in HTML
□ Confirm database changes reflect on website automatically
```

**Rule:** If data changes in the database but not on the website, assume hardcoded HTML until proven otherwise.

---

## Working Style Preferences

**WE ARE NOT QUICK FIX BEINGS. Fix things properly — root cause, not workarounds.**

- Debug the actual issue (path resolution, script loading, CORS, etc.)
- Only use workarounds as temporary measures while debugging
- When automation fails, fix the automation — not just the immediate symptom

**CONFIRM BEFORE ACTING:** When user asks me to do something, I must:
1. State my plan clearly
2. Wait for user confirmation
3. Only then implement

This prevents wasting time on wrong approaches and respects user's expertise.

---

## Deep Dive Generation Process (BURNED INTO MEMORY)

**THE DEEP DIVES ARE THE POINT** — every insight MUST have a Deep Dive.

### Current State:
- Deep Dives are stored in `deep_dive_content` table, keyed by `insight_id`
- Website matches via `insight_id` (not title) since 2026-02-22 fix
- 14 original deep dives were manually hardcoded in `populate_deepdives.py`
- New deep dives are generated via AI or basic fallback

### When Insights Lack Deep Dives:

**Option 1: AI-Generated (Preferred)**
```bash
cd ~/.openclaw/workspace/pipeline
python3 generate_deepdives.py
```
- Uses Moonshot/Kimi API (cheapest option)
- Generates comprehensive analysis with tickers, thesis, risks, catalysts
- May hang silently due to output buffering — if so, use Option 2

**Option 2: Basic Fallback (Quick)**
```bash
cd ~/.openclaw/workspace/pipeline
python3 << 'EOF'
import sqlite3, json
from pathlib import Path
from datetime import datetime

DB = Path.home() / ".openclaw/workspace/pipeline/dashboard.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

c = conn.execute('''
    SELECT li.id, li.title, li.summary, li.key_takeaway 
    FROM latest_insights li
    LEFT JOIN deep_dive_content ddc ON li.id = ddc.insight_id
    WHERE ddc.id IS NULL AND li.display_on_main = 1
''')

for row in c.fetchall():
    overview = (row['summary'] or row['key_takeaway'] or '')[:500]
    conn.execute("""
        INSERT INTO deep_dive_content 
        (insight_id, overview, key_takeaways_detailed, investment_thesis,
         ticker_analysis, positioning_guidance, risk_factors, contrarian_signals, 
         catalysts, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        row['id'], overview, json.dumps([row['key_takeaway'] or 'See summary']),
        row['key_takeaway'] or overview, json.dumps({}),
        "Review insight summary for positioning guidance",
        json.dumps(["Market conditions may change"]),
        json.dumps(["Consider opposing viewpoints"]),
        json.dumps(["Monitor source for updates"]),
        datetime.now().isoformat()
    ))
    print(f"Created deep dive for: {row['title'][:40]}...")

conn.commit()
conn.close()
print("Done!")
EOF
```

**Always After Creating Deep Dives:**
```bash
python3 export_data.py
cd ../site && git add -A && git commit -m "Add deep dives" && git push origin main
```

---

## Security Incident (Fixed 2026-02-15)

- Hardcoded Gmail App Password was in `pipeline/ingest.py` — now removed
- Password loaded from `.env` file via `python-dotenv`
- Old password rotated; new one must be set in `pipeline/.env`

**To set up Gmail access:**
```bash
cd ~/.openclaw/workspace/pipeline
cp .env.example .env
# Add: GMAIL_APP_PASSWORD=your-app-password
```
Generate App Password: https://myaccount.google.com/apppasswords

---

## Podcast Curation Rules

Bitcoin, blockchain, crypto, and digital asset podcasts should **NOT** be skipped — high-priority investment topics.

---

## Email Account
- jsheppard8989@gmail.com (Gmail)
- Used for: Newsletter ingestion
- Folder: NEWSLETTERS (label for processing)

---

## Pushover Notifications

**Script:** `~/.openclaw/workspace/pushover.sh`  
**Usage:** `./pushover.sh "Title" "Message" [priority]`

Priority: `-2` silent, `-1` quiet, `0` normal, `1` high, `2` emergency

Also: `~/.openclaw/workspace/send_imessage.sh` — two-way iMessage (Jared: +16306437437)

---

## Website Architecture

**Title:** "AI, Finance, and Technology: Scarcity & Abundance"  
**Hosted:** GitHub Pages (auto-deploy on push to main)  
**Site files:** `~/.openclaw/workspace/site/`  
**Live URL:** Configured via `site/CNAME`

**Layout:** 3-column grid (2fr 3fr 2fr)
- **Left Column:** Digital Definitions + Contact Form + Suggested New Terms
- **Middle Column:** Latest Insights + AI Alpha & Asset Atrophy (tickers)
- **Right Column:** The Overton Window + Second Order F-X

**Key Features:**
- Live price data from Yahoo Finance (47 primary + 9 second-order tickers)
- Title bar: QQQ price on left, BTC price on right
- Ticker cards with conviction indicators, hidden plays, price data
- Second Order F-X: 9 supply chain tickers (single column)
- Contact form with verification and weekly updates opt-in
- Archive page at `archive.html`
- Disclaimer at bottom

**Data Flow:** `Database → export → site/data/data.js → Website (dynamic load)`  
**Data files:** `site/data/data.js`, `ticker_scores.json`, `podcast_summaries.json`, `archive.json`

---

## Enhanced Stock Scoring System

**Multi-Factor Scoring (0-100+ scale):**
- Base: 10 pts per mention
- Conviction: 0-100 (keywords: "deep dive", "thesis", "conviction" = high; "tracking", "watching" = low)
- Source Diversity: 2+ sources = 1.5x, 3+ sources = 2x; Tier 1 = 2x
- Contrarian: "unloved/underowned" = +20; "crowded/overowned" = -30
- Timeframe: "long term" = +5
- Recency: first mention within 30 days = +15
- Hidden Play Bonus: supply chain beneficiaries = +15

**Hidden Play Mapping:**
- NVDA → Power (NEE, CEG, VST), Cooling (CWST), Networking (ANET, AVGO)
- GOOGL → Cloud Infrastructure (ANET, NET), AI Training (SNOW, PLTR)
- MSFT → Enterprise AI (CRM, NOW), Azure Ecosystem (SNOW, DDOG)

**Source Weighting:**
- Podcasts/Transcripts: 2.0x
- Newsletters (standard): 0.5x
- Newsletters (disruption keywords): 1.5x

---

## Pipeline Structure

```
pipeline/
├── auto_pipeline.py         # PRIMARY: Fully automated end-to-end pipeline
├── run_pipeline.py          # Legacy orchestrator (still present)
├── analyze_transcript.py    # AI-powered transcript analysis (GPT-4o-mini)
├── export_data.py           # Standalone data export (for midday price refresh)
├── ingest.py                # Fetch emails from Gmail
├── curate.py                # Podcast episode curation
├── fetch_latest.py          # Download & transcribe latest episodes
├── fetch_prices.py          # Price data only (cheap, no AI)
├── db_manager.py            # SQLite database operations
├── archive_manager.py       # Manual archive control CLI
├── morning_curator.py       # (DEPRECATED - replaced by auto_pipeline)
├── approval_processor.py    # (DEPRECATED - replaced by auto_pipeline)
├── vote_receiver.py         # Local HTTP server for vote capture
├── process_votes.py         # Processes votes, promotes/rejects terms
├── manage_suggested_terms.py # Extracts terms from content
├── dashboard.db             # SQLite database
├── inbox/                   # Processed newsletter JSON files
├── transcripts/             # Podcast transcripts (.txt)
├── processed/               # Tracks which transcripts are analyzed
└── analysis/                # Top picks reports
```

**Key known bug (as of 2026-02-19):** `analyze_transcript.py` has a DB cursor bug (`_GeneratorContextManager has no cursor`) — uses `db._get_connection()` directly instead of `with`. Also ticker extraction returns 0 mentions — `process_all_transcripts()` isn't calling `add_ticker_mention()` properly. Both need fixing.

---

## Scheduled Jobs (OpenClaw Cron — NOT system crontab)

| Time (CST) | Job | Description |
|------------|-----|-------------|
| **7:00am** | Morning Analysis & Publish | Analyze unprocessed transcripts + newsletters, export, push to GitHub, send iMessage summary to Jared |
| **12:00pm** | Midday Price Refresh | `fetch_prices.py` + `export_data.py` + git push only — no AI, cheap |
| **10:00pm** | Evening Full Pipeline | `auto_pipeline.py` — fetch new podcasts, transcribe, analyze, import newsletters, score, export, push |

All jobs use `model: moonshot/kimi-k2-thinking` in isolated sessions.  
**Note:** System crontab is empty — all scheduling is via OpenClaw cron.  
**Model note:** Use `moonshot/kimi-k2.5` for cron jobs — confirmed working. `kimi-coding/kimi-k2-thinking` 401s (provider URL broken). `moonshot/kimi-k2-thinking` shows as MISSING in OpenClaw. Only `moonshot/kimi-k2.5` is confirmed functional for isolated/cron sessions.

---

## Database Schema

SQLite at `pipeline/dashboard.db`
- `ticker_mentions` — All mentions with source attribution and weighted_score
- `podcast_episodes` — Episode metadata, summaries, is_processed/added_to_site flags
- `newsletters` — Ingested newsletter data
- `daily_scores` — Aggregated daily rankings for website
- `overton_terms` — Emerging terminology tracking
- `definitions` — Glossary of investment terms
- `latest_insights` — Insight cards for main page (display_on_main flag)
- `suggested_terms` — User-votable new terms (status: pending/promoted/rejected)

**Auto-Archive Rules (run by pipeline):**
- Insights older than 14 days → archived (keep most recent 5 on main)
- Definitions outside top 10 by votes → archived
- Overton terms older than 90 days OR status='graduated' → archived

---

## Suggested Terms & Definitions Voting

- Pipeline extracts new terms → `suggested_terms` table (status='pending')
- Top 3 display on website under "Suggested New Terms"
- 👍/👎 voting on site; threshold = 10 votes either way
- 10+ upvotes → auto-promote to Definitions; 10+ downvotes → auto-reject
- **Local:** votes sync via `vote_receiver.py` (localhost:8765)
- **GitHub Pages:** click "🔄 Sync Votes" → export votes.json → commit

---

## Website Contact Form

**Backend:** `~/.openclaw/workspace/contacts.py`  
**Storage:** `contacts.json` (verified), `pending_contacts.json` (pending), `contact_log.txt`

Users opt-in for weekly updates; reply STOP to unsubscribe.

---

## Content Delivered to Website (as of 2026-02-19)

5 insight cards manually written and pushed:
1. Dario Amodei: Near End of the Exponential
2. Jack Mallers: Japan, AI & Bitcoin Liquidity Shock
3. Paul Krugman: Dollar Resilience & AI Deflation Risk
4. Sam Altman: AI CEO Vision / 5-Year Plans Obsolete
5. Noor Siddiqui: Orchard & Genetic Health Revolution

Seeded 17 ticker mentions: BTC, NVDA, MSFT, GOOGL, MSTR, COIN, etc.

---

## Overton Window Tracker

Terms currently tracked/on-site:
- **Neuralink Moment** — BCIs shifting from experimental to consumer-ready
- **Sovereign Individual Thesis** — High-net-worth decoupling from traditional jurisdictions
- **Compute Arbitrage** — Exploiting AI compute price differentials across regions
- **Regulatory Moat** — Competitive advantage through compliance complexity

Criteria: 2+ podcast appearances, direct market implications, not yet mainstream financial media.
