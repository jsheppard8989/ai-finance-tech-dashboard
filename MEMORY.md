# Memory Notes

## 🚨 CRITICAL WEBSITE AUDIT LESSON (2026-02-16) 🚨

**I FAILED to properly audit the website. This is UNACCEPTABLE.**

### The Mistake:
- Insights section was **completely hardcoded in HTML**
- I ran an "audit" and didn't catch this
- Only discovered it when user asked why new insights weren't appearing
- **Hardcoded data in a dynamic website is the #1 red flag**

### Audit Checklist (MANDATORY for all future audits):
```
□ Search for hardcoded dates: grep -E "(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+[0-9]{1,2}" index.html
□ Search for hardcoded titles: grep -E "<strong>.*:</strong>" index.html
□ Verify ALL content sections load from dashboardData
□ Check that no content is manually written in HTML
□ Confirm database changes reflect on website automatically
```

### Rule:
**If data changes in the database but not on the website, assume hardcoded HTML until proven otherwise.**

### What I Should Have Done:
1. Added a new insight to the database
2. Checked if it appeared on the website
3. When it didn't, immediately suspected hardcoded HTML
4. Fixed the root cause (dynamic loading) instead of manually adding to HTML

**This was a systemic failure. Never again.**

---

## Working Style Preferences (2026-02-15)

**WE ARE NOT QUICK FIX BEINGS. We are do shit right once and be done with it creations.**

**Fix things properly as we go** — Don't default to quick fixes like:
- Embedding data directly in HTML instead of fixing the root loading issue
- Using default fallback data instead of debugging why real data isn't loading
- Workarounds that mask underlying problems
- Manual workarounds when the automation is broken

**Preferred approach:**
- Debug the actual issue (path resolution, script loading, CORS, etc.)
- Fix the root cause
- Only use workarounds as temporary measures while debugging
- When automation fails, fix the automation—not just the immediate problem

---

## Security Incident (Fixed 2026-02-15)

**Issue:** Hardcoded Gmail App Password was present in `pipeline/ingest.py`

**Impact:** Password was exposed in code (now rotated)

**Resolution:**
- ✅ Removed hardcoded password from source code
- ✅ Password now loaded from environment variables
- ✅ Added `.env.example` template
- ✅ Updated `.gitignore` to exclude `.env` files
- ✅ Added runtime check with helpful error message
- ✅ Updated README with security warnings

**Required Action:**
```bash
# 1. Generate new App Password (old one is compromised)
# Go to: https://myaccount.google.com/apppasswords
# Delete old 'Stock Pipeline' password
# Generate new one

# 2. Create .env file
cd pipeline
cp .env.example .env
# Edit .env and add your NEW app password

# 3. Set environment variable (for current session)
export GMAIL_APP_PASSWORD='your-new-app-password'
```

**Security Best Practices Going Forward:**
- Never commit `.env` files
- Use environment variables for all credentials
- Rotate passwords if accidentally exposed
- Enable GitHub secret scanning on repository

---

## Podcast Curation Rules

**As of 2026-02-13:**
- Bitcoin, blockchain, crypto, and digital asset podcasts should **NOT** be skipped
- These are high-priority investment topics
- Keywords added to curation system: bitcoin, btc, blockchain, satoshi, lightning network, altcoin, ethereum, eth, defi, web3, digital asset

## Suggested Terms & Definitions Voting (2026-02-18)

**Status:** ✅ Active

### How It Works

**1. Term Discovery**
- Pipeline scans podcast transcripts and newsletters for new investment terms
- Extracted terms go to `suggested_terms` table with status='pending'
- Top 3 suggestions display on website under "Suggested New Terms"

**2. User Voting (on website)**
- 👍 Upvote terms you want added to Definitions
- 👎 Downvote terms to skip/remove them
- **Threshold:** 10 votes either way triggers auto-action

**3. Vote Sync**
- **Local viewing:** Votes auto-sync to `votes.json` via localhost:8765
- **GitHub Pages:** Click "🔄 Sync Votes" button to export votes.json, then commit to repo

**4. Auto-Processing (Pipeline Step 9b)**
```
10+ upvotes  → Auto-promote to Definitions (display_on_main=1)
10+ downvotes → Auto-reject (status='rejected')
```

**Scripts:**
- `pipeline/vote_receiver.py` - Local HTTP server for vote capture
- `pipeline/process_votes.py` - Processes votes and promotes/rejects terms
- `pipeline/manage_suggested_terms.py` - Extracts terms from content

**To run manually:**
```bash
cd ~/.openclaw/workspace/pipeline
python3 process_votes.py  # Process pending votes
python3 manage_suggested_terms.py  # Extract new terms from content
```

---

## Scheduled Jobs

**Morning Newsletter Check**
- Time: 8:30am CST daily
- Task: Check NEWSLETTERS folder in Gmail, extract tickers, generate top picks

**Podcast Transcription**
- Time: 10:00pm CST daily
- Task: Fetch latest episodes from all feeds, download, transcribe with Whisper

## Email Account
- jsheppard8989@gmail.com (Gmail)
- Used for: Newsletter ingestion
- Folder: NEWSLETTERS (label for processing)

## Pushover Notifications

**Status:** ✅ Active as of 2026-02-14

**Script:** `~/.openclaw/workspace/pushover.sh`

**Usage:**
```bash
./pushover.sh "Title" "Message" [priority]
```

**Priority levels:**
- `-2` — Silent (no notification)
- `-1` — Quiet (no sound/vibration)
- `0` — Normal (default)
- `1` — High priority (bypass quiet hours)
- `2` — Emergency (requires acknowledgment)

**Current integrations:**
| Event | Priority | Description |
|-------|----------|-------------|
| Newsletter Analysis | 0 | Daily 8:30am — top 5 picks (Pushover + iMessage) |
| Podcast Transcription | 0 | Silent on success, iMessage alert on failures |
| Job Failures | 1 | Immediate iMessage alert if pipeline fails |
| Manual reach-out | - | Two-way iMessage anytime via +16306437437 |

**Scripts:**
- `~/.openclaw/workspace/pushover.sh` — One-way push notifications
- `~/.openclaw/workspace/send_imessage.sh` — Two-way iMessage replies

**Future alerts to consider:**
- [ ] VIX spike >30
- [ ] Bitcoin daily move >10%
- [ ] New Overton Window term detected (2+ mentions)
- [ ] Ticker mention surge (5+ new mentions in 24h)

## Website Architecture (As of 2026-02-14)

**Title:** "AI, Finance, and Technology: Scarcity & Abundance"

**Layout:** 3-column grid (2fr 3fr 2fr)
- **Left Column:** Digital Definitions to Define Directions + Contact Form
- **Middle Column:** Latest Insights + AI Alpha & Asset Atrophy (tickers)
- **Right Column:** The Overton Window + Second Order F-X

**Key Features:**
- Live price data from Yahoo Finance (47 tickers with 2-week % change)
- Title bar: QQQ $price ±change on left, ±change $price ₿ on right
- Enhanced ticker cards with conviction indicators, hidden plays, price data
- Second Order F-X: 9 supply chain tickers displayed (single column)
- Contact form with verification and weekly updates opt-in
- Disclaimer at bottom

## Enhanced Stock Scoring System

**As of 2026-02-14:**

**Multi-Factor Scoring (0-100+ scale):**
| Factor | Weight | Description |
|--------|--------|-------------|
| Mention Score | Base | 10 pts per mention |
| Conviction | 0-100 | Detected via keywords: "deep dive", "thesis", "conviction" = high; "tracking", "watching" = low |
| Source Diversity | Multiplier | 2+ sources = 1.5x, 3+ sources = 2x; Tier 1 sources (hedge funds, elite podcasts) = 2x |
| Contrarian Signal | ±30 | "Unloved", "underowned" = +20; "Crowded", "overowned" = -30 |
| Timeframe | +5 | "Long term" mentions get bonus |
| Recency | +15 | First mention within 30 days |
| Hidden Play Bonus | +15 | Supply chain beneficiaries when megacap mentioned |

**Categories Generated:**
1. **Consensus Buys** — High score + multiple sources + high conviction
2. **Hidden Gems** — Supply chain plays, second-order beneficiaries
3. **Contrarian Plays** — Explicit contrarian signals
4. **Early Signals** — First mentions, emerging themes
5. **Thematic Picks** — Best exposure to detected macro themes

**Hidden Play Mapping:**
- NVDA → Power (NEE, CEG, VST), Cooling (CWST), Networking (ANET, AVGO)
- GOOGL → Cloud Infrastructure (ANET, NET), AI Training (SNOW, PLTR)
- MSFT → Enterprise AI (CRM, NOW), Azure Ecosystem (SNOW, DDOG)

**Scripts:**
- `analyze_enhanced.py` — New multi-factor analysis
- `analyze.py` — Legacy mention-counting (deprecated)
- `generate_charts.py` — Chart generation for 47 tickers (primary + second-order)
- Charts and price data updated daily at 9:00am CST
- Price data embedded in HTML for reliability

## Website Contact Form

**Status:** ✅ Active as of 2026-02-14

**Location:** Left column under Suggested New Terms

**Backend Script:** `~/.openclaw/workspace/contacts.py`

**Commands:**
```bash
python3 contacts.py add "Name" "email@example.com" "Message"
python3 contacts.py verify "email@example.com" 123456
python3 contacts.py subscribe "email@example.com"
python3 contacts.py unsubscribe "email@example.com"
python3 contacts.py list
```

**Features:**
- Contact form asks if they want weekly updates (checkbox)
- Welcome message asks them to reply YES to subscribe (opt-in, not automatic)
- `weeklyUpdates` field: `null` = asked but no response, `true` = subscribed, `false` = declined/unsubscribed
- Users can reply STOP anytime to unsubscribe

**Storage:**
- `~/.openclaw/workspace/contacts.json` — Verified contacts with `weeklyUpdates` status
- `~/.openclaw/workspace/pending_contacts.json` — Pending verification
- `~/.openclaw/workspace/contact_log.txt` — Activity log

## Pipeline Structure
```
pipeline/
├── ingest.py              # Fetch emails from Gmail
├── analyze_enhanced.py    # Multi-factor scoring with conviction detection
├── analyze.py             # Legacy: Basic ticker scoring
├── research.py            # Advanced theme extraction & hidden plays
├── curate.py              # Podcast episode curation
├── fetch_latest.py        # Download & transcribe latest episodes
├── db_manager.py          # SQLite database operations
├── run_pipeline.py        # Master orchestrator
├── schema.sql             # Database schema
├── dashboard.db           # SQLite database (auto-created)
├── inbox/                 # Processed emails (JSON)
├── transcripts/           # Podcast transcripts
├── research/              # Research reports
└── analysis/              # Top picks reports (enhanced)
```

## Database-Driven Pipeline (As of 2026-02-15)

**New Architecture:** SQLite-based data management with automated website updates

### Database Schema
- `ticker_mentions` — All ticker mentions with source attribution and weights
- `podcast_episodes` — Full episode metadata including summaries
- `newsletters` — Ingested newsletter data
- `daily_scores` — Aggregated daily rankings for website
- `overton_terms` — Emerging terminology tracking
- `definitions` — Glossary of investment terms

### Source Weighting (Implemented)
| Source Type | Weight | Rationale |
|-------------|--------|-----------|
| **🎙️ Podcasts/Transcripts** | 2.0x | Drive primary focus |
| **📧 Newsletters (standard)** | 0.5x | Reduced base weight |
| **📧 Newsletters (disruption)** | 1.5x | Boost when disruption keywords detected |

### Disruption Keywords (Newsletter Boost)
```
disruption, disruptive, paradigm shift, game changer, breakthrough,
transformation, revolutionary, industry changing, once in a generation,
tipping point, inflection point, sea change, watershed moment
```

### Running the Pipeline
```bash
cd ~/.openclaw/workspace/pipeline
python3 run_pipeline.py
```

This single command:
1. **Curates** new podcast episodes
2. **Downloads** and transcribes audio
3. **Ingests** newsletters from Gmail
4. **Imports** all data to database
5. **Analyzes** with weighted scoring (podcasts prioritized)
6. **Aggregates** daily ticker scores
7. **Auto-archives** old content (14/90 day rules)
8. **Generates** price charts
9. **Exports** data.js for website

### Pipeline Output Summary
```
Results:
  ✓ curate: True
  ✓ fetch: True
  ✓ ingest: True
  ✓ import_podcasts: 3
  ✓ import_newsletters: 5
  ✓ analysis: True
  ✓ aggregate: 30
  ✓ auto_archive: {'insights': 2, 'overton': 1, 'definitions': 3}  ← Auto-archive results
  ✓ charts: True
  ✓ export: {...}
  ✓ generate_js: True

Database Stats:
  ticker_mentions: 150
  podcast_episodes: 12
  newsletters: 25
  daily_scores: 30
  today_mentions: {'podcast': 8, 'newsletter': 3}
```

### Website Data Flow
```
Database → JSON Export → data.js → Website (dynamic load)
```

The website now loads:
- `data/data.js` — Combined ticker scores + podcast summaries
- `data/ticker_scores.json` — Individual scores (fallback)
- `data/podcast_summaries.json` — Podcast data (fallback)

If exports aren't available, falls back to embedded default data.

### Benefits
✅ Podcasts now drive ticker focus (4x weight vs newsletters)  
✅ Newsletters only matter when discussing disruption  
✅ All data centralized in SQLite (queryable, auditable)  
✅ Single command updates entire website  
✅ No manual HTML editing for content updates  
✅ Historical tracking built-in  
✅ Easy to extend with new data sources

## Content Archive System (As of 2026-02-15)

**Problem:** Main page can only display limited content. Need to rotate old content while keeping it accessible.

**Solution:** Archive page with database-driven content lifecycle.

### Content Lifecycle

```
┌─────────────────────────────────────────────────────────────┐
│  ACTIVE (Main Page)                                         │
│  • Latest Insights: Last 5 episodes                         │
│  • Definitions: Top 10 by votes/relevance                   │
│  • Overton Window: Active emerging terms (≤8)               │
└─────────────────────────────────────────────────────────────┘
                              ↓
                    (auto-archive after N days
                     or manual archive)
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  ARCHIVED (Archive Page)                                    │
│  • Searchable historical content                            │
│  • Organized by type (Insights/Definitions/Overton)         │
│  • Shows when/why archived                                  │
└─────────────────────────────────────────────────────────────┘
```

### Archive Page (`archive.html`)
- **URL:** `/archive.html`
- **Features:**
  - Tabbed navigation (Insights / Definitions / Overton)
  - Search across all archived content
  - Shows archive date and reason
  - Stats counters for each category

### Database Fields for Archiving

**latest_insights:**
- `display_on_main` - Boolean, show on main page?
- `archived_date` - When moved to archive
- `archived_reason` - Why archived (e.g., "Superseded by newer episode")

**definitions:**
- `display_on_main` - Boolean
- `archived_date` - When moved
- `archived_reason` - Why archived
- `display_order` - Priority on main page

**overton_terms:**
- `display_on_main` - Boolean
- `status` - 'active', 'graduated' (mainstream), or 'archived'
- `archived_date` - When moved
- `archived_reason` - Why archived

### Auto-Archive Rules (Implemented)
The `run_pipeline.py` automatically archives content based on these rules:

| Content Type | Rule | Action |
|--------------|------|--------|
| **Insights** | Older than 14 days | Archive all but most recent 5 |
| **Definitions** | Outside top 10 by votes | Archive lower-voted terms |
| **Overton Terms** | Older than 90 days OR status='graduated' | Archive to historical |

**When pipeline runs:**
```
Step 6b: Auto-Archiving Content
  ✓ Auto-archived X items: {'insights': 2, 'overton': 1, 'definitions': 3}
```

### Manual Archive Process
Use `archive_manager.py` CLI for manual control:

```bash
# List content with IDs
python3 archive_manager.py list insights
python3 archive_manager.py list definitions
python3 archive_manager.py list overton

# Archive specific item
python3 archive_manager.py archive insights 123 --reason "Replaced by newer episode"
python3 archive_manager.py archive definitions 456 --reason "No longer relevant"
python3 archive_manager.py archive overton 789 --reason "Term now mainstream"

# Restore to main page
python3 archive_manager.py restore insights 123

# View archive stats
python3 archive_manager.py stats
```

**Programmatic access:**
```python
from db_manager import get_db
db = get_db()

# Archive manually
db.archive_item('insight', item_id=123, reason="Custom reason")

# Get main page content only
main_content = db.get_main_page_content()

# Get all archive data
archive = db.export_archive_data()
```

### Export for Archive Page
Archive data exported to `data/archive.json`:
```json
{
  "insights": [...],
  "definitions": [...],
  "overton": [...]
}
```

### Navigation
- Footer links: "📚 Archive" • "🏠 Dashboard"
- Archive page has "← Back to Dashboard" link

## Overton Window Tracker

**Purpose:** Track emerging terminology/concepts from podcasts that are on the brink of mainstream investment discourse.

**Current Terms (on site):**
| Term | Source | Description | Status |
|------|--------|-------------|--------|
| Neuralink Moment | Network State Podcast | BCIs shifting from experimental to consumer-ready | 🟡 Emerging |
| Sovereign Individual Thesis | Monetary Matters | High-net-worth decoupling from traditional jurisdictions | 🟡 Emerging |
| Compute Arbitrage | a16z Live | Exploiting AI compute price differentials across regions | 🟡 Emerging |
| Regulatory Moat | Jack Mallers Show | Competitive advantage through compliance complexity | 🟡 Emerging |

**Candidate Terms (watching):**
- *None currently — scan new transcripts for patterns*

**Criteria for adding:**
- Term appears in 2+ podcast episodes
- Concept has direct market/investment implications
- Not yet widely used in mainstream financial media
- Clear, concise description possible in 1-2 sentences

## GitHub Pages Deployment (As of 2026-02-15)

**Live URL:** `https://YOUR_USERNAME.github.io/ai-finance-tech-dashboard`

### Setup Steps

1. **Run setup script:**
   ```bash
   cd ~/.openclaw/workspace
   ./setup_github.sh
   ```

2. **Create GitHub repository:**
   - Go to https://github.com/new
   - Name: `ai-finance-tech-dashboard`
   - Make it **Public**
   - Don't initialize with README

3. **Push code:**
   ```bash
   git push -u origin main
   ```

4. **Enable GitHub Pages:**
   - Repository → Settings → Pages
   - Source: "GitHub Actions"

5. **Access your site:**
   - Wait 2-3 minutes
   - Visit: `https://YOUR_USERNAME.github.io/ai-finance-tech-dashboard`

### Automated Deployment

The pipeline now auto-pushes to GitHub:

```
run_pipeline.py
  ├── ... (generates data)
  └── push_to_github()  ← Auto-commits and pushes
         └── GitHub Actions deploys to Pages
```

### Custom Domain (Optional)

1. Edit `site/CNAME`:
   ```
   scarcityabundance.com
   ```

2. Configure DNS with your provider:
   ```
   CNAME scarcityabundance.com → YOUR_USERNAME.github.io
   ```

3. Enable HTTPS in GitHub Pages settings

### Files Added for Deployment

```
.github/
├── workflows/
│   └── deploy.yml         # GitHub Actions workflow
├── setup_github.sh        # Setup helper script
└── README.md              # Documentation
```

### Troubleshooting

**"Using default data" warning on archive page:**
- This is normal when opening file locally
- Use `python3 -m http.server 8000` for local testing
- Or view the deployed site on GitHub Pages

**Push fails:**
- Check git remote: `git remote -v`
- Verify GitHub token permissions
- Run manually: `git push origin main`

---

## Pipeline Fix: Transcript Analysis (2026-02-16)

**Problem:** Website data was stale (33+ hours old). The pipeline was downloading and transcribing podcasts, but transcripts were never being analyzed to extract ticker mentions and insights.

**Root Cause:** `run_pipeline.py` had a stub `import_podcasts_to_db()` function that only logged transcript filenames instead of actually processing them with AI.

**Solution:** Built proper automation:

1. **Created `analyze_transcript.py`** — New module that:
   - Reads transcript files from `transcripts/`
   - Uses OpenAI GPT-4o-mini to extract structured data (summary, key takeaways, ticker mentions with sentiment/conviction)
   - Adds PodcastEpisode and TickerMention records to database
   - Tracks processed transcripts to avoid reprocessing

2. **Updated `run_pipeline.py`** — Replaced stub with actual call to `analyze_transcript.process_all_transcripts()`

3. **Created `export_data.py`** — Standalone script for midday price refreshes (was missing, causing cron job to fail)

4. **Updated cron jobs** — All three automated jobs now call the unified pipeline correctly:
   - 8:30am: Full pipeline with newsletter focus
   - 9:00am: Chart/price refresh only (cheap)
   - 10:00pm: Full pipeline with podcast focus

**New Pipeline Files:**
```
pipeline/
├── analyze_transcript.py    # NEW: AI-powered transcript analysis
├── export_data.py           # NEW: Standalone data export for cron
└── processed/               # NEW: Tracks which transcripts are processed
```

**To run manually:**
```bash
cd ~/.openclaw/workspace/pipeline
python3 run_pipeline.py
```

**Cost note:** Analyzing a 1-hour transcript costs ~$0.05-0.10 in OpenAI API calls. With ~7 transcripts queued, expect ~$0.50-0.70 to clear the backlog.

---

## Morning Podcast Approval Workflow (2026-02-16)

**New Workflow:** Instead of automatically processing all podcasts at 8:30am, Jared now receives an iMessage at **6:00am** with a list of available podcasts and can choose which ones to process.

### How It Works

```
6:00am CST → iMessage sent to Jared with podcast list
                    ↓
            Jared replies with selection:
            • "PROCESS ALL" → analyze all episodes
            • "SKIP ALL" → skip today's batch
            • "1,3,5" → process only episodes 1, 3, and 5
                    ↓
            6AIndolf processes approved episodes
                    ↓
            Website updated with new insights
```

### Scripts

**`morning_curator.py`** — Runs at 6am, sends iMessage:
```bash
python3 morning_curator.py
```

**`approval_processor.py`** — Handles Jared's reply:
```bash
# Example: Process episodes 1, 3, and 5
python3 approval_processor.py "1,3,5"

# Example: Process all
python3 approval_processor.py "process all"

# Example: Skip all
python3 approval_processor.py "skip"
```

### Current Queue (As of 2026-02-16)

| # | Podcast | Episode | Topic |
|---|---------|---------|-------|
| 1 | Monetary Matters | - | Carson Block on short selling, AI pretenders, mining |
| 2 | Monetary Matters | - | Milton Berg technical analysis, gold/silver signals |
| 3 | Moonshots with Peter Diamandis | EP #229 | **Brett Adcock: Humanoid Run on Neural Net, $50T Market** |
| 4 | Moonshots with Peter Diamandis | EP #230 | **Sam Altman's Succession Plan, AI CEO Arrives** |
| 5 | a16z Live | - | How Startups are Fixing Healthcare |
| 6 | The Jack Mallers Show | - | Bonds, debt, markets & Bitcoin |

**Note:** Incorrect "Moonshot Podcast" episodes cleared and replaced with correct **Peter Diamandis** episodes from Podscan.fm.

### Podcast Feed Updates (2026-02-16)

**Fixed:** Replaced incorrect podcast feed
- ❌ ~~`https://feeds.megaphone.fm/moonshot`~~ (wrong podcast - "The Moonshot Podcast")
- ✅ **Now using Podscan.fm** for direct transcript access

**Peter Diamandis episodes manually added:**
- EP #229: Brett Adcock on Figure AI, humanoid robots, neural nets
- EP #230: Sam Altman's AI CEO succession plan, job loss, "Solve Everything" paper

### Cron Schedule (Updated)

| Time | Job | Description |
|------|-----|-------------|
| **6:00am** | Morning Curation | Send iMessage with podcast list for approval |
| 9:00am | Price Refresh | Update charts only (cheap, no AI) |
| 10:00pm | Evening Pipeline | Download and transcribe new podcasts |

**Note:** The newsletter check (previously 8:30am) is now integrated into the morning workflow. Podcast analysis only happens after Jared approves which episodes to process.
