# AI, Finance, Tech: Scarcity & Abundance

A curated dashboard aggregating investment insights from podcasts and newsletters, with automated analysis and visualization.

![Dashboard](https://img.shields.io/badge/Dashboard-Live-brightgreen)
![Data](https://img.shields.io/badge/Data-Auto--updated-blue)
![License](https://img.shields.io/badge/License-MIT-yellow)

## 🌐 Live Site

**URL:** `https://YOUR_USERNAME.github.io/ai-finance-tech-dashboard`

*(Replace YOUR_USERNAME with your actual GitHub username after setup)*

## 📊 Features

- **AI Alpha & Asset Atrophy** - Multi-factor stock scoring (podcasts weighted 4x newsletters)
- **Latest Insights** - Curated podcast highlights with Deep Dive modals
- **Digital Definitions** - Investment glossary with voting system
- **The Overton Window** - Emerging investment terminology tracker
- **Second Order Effects** - Supply chain beneficiaries and hidden plays
- **Archive System** - Searchable historical content with auto-aging

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- Git
- GitHub account
- Gmail App Password (for newsletter ingestion)

### ⚠️ Security Notice

**IMPORTANT:** This project handles sensitive API credentials. Never commit `.env` files or hardcoded passwords to GitHub!

The repository includes:
- `.env.example` - Template showing required variables (safe to commit)
- `.env` - Your actual credentials (automatically ignored by Git)
- `.gitignore` - Prevents accidental commits of sensitive files

**Required Setup:**
```bash
cd pipeline
cp .env.example .env
# Edit .env with your actual credentials
nano .env  # or use your preferred editor
```

**GitHub Secret Scanning:** If you've accidentally committed credentials:
1. Change the password/API key immediately
2. Use [BFG Repo-Cleaner](https://rtyley.github.io/bfg-repo-cleaner/) or git-filter-branch to remove from history
3. Or create a new repository and migrate (safest option)

### Local Development

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/ai-finance-tech-dashboard.git
cd ai-finance-tech-dashboard

# Install dependencies
pip install -r pipeline/requirements.txt

# Run the pipeline (generates data and charts)
cd pipeline
python3 auto_pipeline.py
# Or analyze-only (no fetch): python3 auto_pipeline.py --analyze-only

# Serve locally for testing
cd ../site
python3 -m http.server 8000
# Open http://localhost:8000
```

### GitHub Pages Setup

1. **Create Repository**
   - Go to GitHub → New Repository
   - Name: `ai-finance-tech-dashboard`
   - Make it Public (required for free GitHub Pages)
   - Don't initialize with README

2. **Push Code**
   ```bash
   cd ~/.openclaw/workspace
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/ai-finance-tech-dashboard.git
   git push -u origin main
   ```

3. **Enable GitHub Pages**
   - Go to repository → Settings → Pages
   - Source: "GitHub Actions"
   - The workflow file is already included

4. **Access Your Site**
   - URL: `https://YOUR_USERNAME.github.io/ai-finance-tech-dashboard`
   - Wait 2-3 minutes for first deployment

## 📁 Project Structure

```
.
├── .github/
│   └── workflows/
│       └── deploy.yml          # GitHub Pages deployment
├── pipeline/
│   ├── schema.sql              # Database schema
│   ├── db_manager.py           # Database operations
│   ├── auto_pipeline.py        # Primary orchestrator (fetch → analyze → export → push)
│   ├── export_data.py          # Website export (data.js, JSONs); used by auto_pipeline
│   ├── run_pipeline.py         # Legacy orchestrator (still present)
│   ├── curate.py               # Podcast curation
│   ├── ingest.py               # Newsletter ingestion
│   ├── analyze_transcript.py   # Transcript AI analysis
│   └── fetch_latest.py         # Fetch & transcribe (queue + worker)
├── site/
│   ├── index.html              # Main dashboard
│   ├── archive.html            # Archive page
│   └── data/                   # Generated data files
│       ├── data.js
│       └── archive.json
└── README.md                   # This file
```

## ⚙️ Configuration

### Environment Variables

Create `.env` in `pipeline/` directory:

```bash
# Email (for newsletter ingestion)
GMAIL_USER=your-email@gmail.com
GMAIL_APP_PASSWORD=your-app-password

# Optional: Pushover notifications
PUSHOVER_TOKEN=your-pushover-token
PUSHOVER_USER=your-pushover-user
```

### Automated Updates

Scheduling is via **OpenClaw cron** (see MEMORY.md and pipeline/README.md). Jobs run `auto_pipeline.py` (full or `--analyze-only`). For system cron instead:

```bash
crontab -e
# Example: full pipeline daily at 7 AM
0 7 * * * cd ~/.openclaw/workspace/pipeline && python3 auto_pipeline.py
```

### Source Weighting

| Source | Weight | Description |
|--------|--------|-------------|
| 🎙️ Podcasts | 2.0x | Drives primary focus |
| 📧 Newsletters | 0.5x | Reduced base weight |
| ⚡ Disruption | 1.5x | Boost when keywords detected |

## 🔧 Pipeline Workflow

```
1. Curate podcasts (RSS feeds)
2. Fetch & transcribe (Whisper)
3. Ingest newsletters (Gmail)
4. Import to database (SQLite)
5. Analyze (weighted scoring)
6. Aggregate (daily rankings)
7. Auto-archive (14/90 day rules)
8. Generate charts
9. Export data.js
10. Deploy to GitHub Pages
```

## 📊 Data Sources

### Podcasts
- The Rundown AI
- Monetary Matters with Jack Farley
- The Jack Mallers Show
- a16z Live
- Network State Podcast

### Newsletters
- Gmail NEWSLETTERS label
- Filtered for relevance
- Disruption keywords boost signal

## 🛠️ Maintenance

### Manual Archive
```bash
cd pipeline
python3 archive_manager.py list insights
python3 archive_manager.py archive insights 123 --reason "Replaced by newer"
```

### Add New Podcast
Edit `curate.py` and add feed URL to `PODCAST_FEEDS`.

### Update Definitions
Edit in database or use `archive_manager.py`.

## 📝 License

MIT License - Feel free to use and modify.

## 🤝 Contributing

This is a personal project, but suggestions welcome via issues.

## 🙏 Credits

Curated by [6AIndolf](https://github.com/YOUR_USERNAME) 🤖🧙‍♂️

Powered by OpenClaw, SQLite, and automated pipelines.