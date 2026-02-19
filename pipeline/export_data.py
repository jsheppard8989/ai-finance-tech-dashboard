#!/usr/bin/env python3
"""
Standalone data export script for website updates.
Called by cron job for midday price refreshes.
"""

import sys
from pathlib import Path
from datetime import datetime
import json

# Add pipeline directory to path
sys.path.insert(0, str(Path(__file__).parent))
from db_manager import get_db


def export_website_data():
    """Export data for website."""
    print("="*60)
    print("Exporting Website Data")
    print("="*60)
    
    db = get_db()
    site_dir = Path.home() / ".openclaw/workspace/site/data"
    site_dir.mkdir(parents=True, exist_ok=True)
    
    stats = db.export_for_website(site_dir)
    print(f"✓ Exported: {stats}")
    return stats


def generate_website_js():
    """Generate JavaScript file with data for website."""
    print("\n" + "="*60)
    print("Generating Website JavaScript")
    print("="*60)
    
    db = get_db()
    site_dir = Path.home() / ".openclaw/workspace/site/data"
    
    # Get all data including archive
    archive = db.export_archive_data()
    print(f"DEBUG: export_archive_data returned {len(archive['insights'])} insights")
    ids = [i['id'] for i in archive['insights']]
    from collections import Counter
    counts = Counter(ids)
    print(f"DEBUG: ID counts: {dict(counts)}")
    main_content = db.get_main_page_content()
    deepdives = db.get_all_deep_dive_content()
    suggested_terms = db.get_suggested_terms_for_website(limit=3)
    
    # Load ticker scores
    try:
        with open(site_dir / 'ticker_scores.json', 'r') as f:
            ticker_scores = json.load(f)
    except FileNotFoundError:
        ticker_scores = []
    
    # Generate data.js that the HTML can load
    # Pre-serialize to avoid f-string issues
    ticker_json = json.dumps(ticker_scores, indent=2)
    archive_json = json.dumps(archive, indent=2)
    main_json = json.dumps(main_content, indent=2)
    deepdives_json = json.dumps(deepdives, indent=2)
    suggested_json = json.dumps(suggested_terms, indent=2)
    
    print(f"DEBUG: archive_json has {archive_json.count(chr(34)+'id'+chr(34))} 'id' keys")
    
    js_content = f"""// Auto-generated data file - {datetime.now().isoformat()}
// DO NOT EDIT MANUALLY

const dashboardData = {{
  generatedAt: "{datetime.now().isoformat()}",
  tickerScores: {ticker_json},
  archive: {archive_json},
  mainContent: {main_json},
  deepDives: {deepdives_json},
  suggestedTerms: {suggested_json}
}};

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {{
  module.exports = dashboardData;
}}
"""
    
    with open(site_dir / 'data.js', 'w') as f:
        f.write(js_content)
    
    total_archive = sum(len(v) for v in archive.values() if isinstance(v, list))
    print(f"✓ Generated data.js with {len(ticker_scores)} tickers, {total_archive} archive items, {len(deepdives)} deep dives, {len(suggested_terms)} suggested terms")
    return True


def main():
    """Run data export."""
    print(f"Data Export Started: {datetime.now()}")
    
    export_website_data()
    generate_website_js()
    
    print(f"\n✓ Data export complete")


if __name__ == "__main__":
    main()
