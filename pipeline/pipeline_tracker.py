#!/usr/bin/env python3
"""
Podcast Pipeline Status Tracker
Tracks episodes through: Downloaded → Transcribed → Analyzed → Published
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Paths
AUDIO_DIR = Path.home() / ".openclaw/workspace/audio"
TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"
DB_PATH = Path.home() / ".openclaw/workspace/pipeline/dashboard.db"
STATE_DIR = Path.home() / ".openclaw/workspace/pipeline/state"
CURATION_LOG = STATE_DIR / "curation_log.json"
STATUS_FILE = STATE_DIR / "pipeline_status.json"

class PodcastPipelineTracker:
    """Track podcast episodes through the processing pipeline."""
    
    STAGES = [
        'downloaded',      # Audio file exists
        'transcribed',     # Transcript file exists
        'analyzed',        # In database as podcast_episode
        'insight_created', # Has insight in latest_insights
        'published'        # On website (in data.js)
    ]
    
    def __init__(self):
        self.status = self._load_status()
        
    def _load_status(self) -> Dict:
        """Load existing status or create new."""
        if STATUS_FILE.exists():
            with open(STATUS_FILE, 'r') as f:
                return json.load(f)
        return {
            'last_updated': datetime.now().isoformat(),
            'episodes': {}
        }
    
    def _save_status(self):
        """Save current status to file."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.status['last_updated'] = datetime.now().isoformat()
        with open(STATUS_FILE, 'w') as f:
            json.dump(self.status, f, indent=2)
    
    def scan_pipeline(self):
        """Scan all directories and database to update status."""
        print("🔍 Scanning podcast pipeline...\n")
        
        # 1. Get approved episodes from curation log
        approved_episodes = self._get_approved_episodes()
        
        # 2. Check each episode's progress
        for episode_id, episode_info in approved_episodes.items():
            self._update_episode_status(episode_id, episode_info)
        
        self._save_status()
        self._print_summary()
        
    def _get_approved_episodes(self) -> Dict:
        """Get list of approved episodes from curation log."""
        episodes = {}
        
        if not CURATION_LOG.exists():
            return episodes
            
        with open(CURATION_LOG, 'r') as f:
            log = json.load(f)
        
        for ep in log.get('episodes', []):
            if ep.get('status') == 'APPROVED':
                # Create unique ID from podcast + title
                ep_id = f"{ep['podcast']}_{ep['title'][:30]}".replace(' ', '_').lower()
                episodes[ep_id] = {
                    'podcast': ep['podcast'],
                    'title': ep['title'],
                    'published': ep.get('published', 'Unknown'),
                    'audio_file': ep.get('audio_file', ''),
                    'keywords': ep.get('matched_keywords', [])
                }
        
        return episodes
    
    def _update_episode_status(self, ep_id: str, episode_info: Dict):
        """Update status for a single episode."""
        if ep_id not in self.status['episodes']:
            self.status['episodes'][ep_id] = {
                'info': episode_info,
                'stages': {},
                'first_seen': datetime.now().isoformat()
            }
        
        status = self.status['episodes'][ep_id]
        
        # Stage 1: Downloaded?
        audio_file = episode_info.get('audio_file', '')
        status['stages']['downloaded'] = {
            'complete': Path(audio_file).exists() if audio_file else False,
            'timestamp': status['stages'].get('downloaded', {}).get('timestamp')
        }
        
        # Stage 2: Transcribed?
        # Look for matching transcript file
        transcript_found = False
        transcript_file = None
        
        # Try to match by filename patterns
        audio_filename = Path(audio_file).stem if audio_file else ''
        for transcript in TRANSCRIPT_DIR.glob('*.txt'):
            # Check if transcript matches audio file
            if audio_filename in transcript.name or \
               self._normalize_name(episode_info['title']) in self._normalize_name(transcript.name):
                transcript_found = True
                transcript_file = str(transcript)
                break
        
        status['stages']['transcribed'] = {
            'complete': transcript_found,
            'file': transcript_file,
            'timestamp': status['stages'].get('transcribed', {}).get('timestamp')
        }
        
        # Stage 3 & 4: Analyzed and in database?
        self._check_database_status(ep_id, episode_info, status)
        
        # Stage 5: Published?
        self._check_published_status(ep_id, episode_info, status)
        
    def _normalize_name(self, name: str) -> str:
        """Normalize name for comparison."""
        return name.lower().replace(' ', '_').replace('-', '_')[:30]
    
    def _check_database_status(self, ep_id: str, episode_info: Dict, status: Dict):
        """Check if episode is in database."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Check podcast_episodes table
        cursor.execute("""
            SELECT id, episode_date, summary 
            FROM podcast_episodes 
            WHERE podcast_name LIKE ? AND episode_title LIKE ?
        """, (f"%{episode_info['podcast']}%", f"%{episode_info['title'][:40]}%"))
        
        episode_row = cursor.fetchone()
        
        status['stages']['analyzed'] = {
            'complete': episode_row is not None,
            'episode_id': episode_row['id'] if episode_row else None,
            'timestamp': status['stages'].get('analyzed', {}).get('timestamp')
        }
        
        # Check if there's a related insight
        if episode_row:
            cursor.execute("""
                SELECT id, title 
                FROM latest_insights 
                WHERE title LIKE ? OR source_name LIKE ?
            """, (f"%{episode_info['title'][:30]}%", f"%{episode_info['podcast']}%"))
            
            insight_row = cursor.fetchone()
            
            status['stages']['insight_created'] = {
                'complete': insight_row is not None,
                'insight_id': insight_row['id'] if insight_row else None,
                'insight_title': insight_row['title'] if insight_row else None,
                'timestamp': status['stages'].get('insight_created', {}).get('timestamp')
            }
        else:
            status['stages']['insight_created'] = {
                'complete': False,
                'timestamp': None
            }
        
        conn.close()
    
    def _check_published_status(self, ep_id: str, episode_info: Dict, status: Dict):
        """Check if episode is in the published data.js."""
        data_js = Path.home() / ".openclaw/workspace/site/data/data.js"
        
        if not data_js.exists():
            status['stages']['published'] = {'complete': False}
            return
        
        # Simple check - look for title in data.js
        with open(data_js, 'r', encoding='utf-8') as f:
            content = f.read()
        
        title_found = episode_info['title'][:30] in content
        
        status['stages']['published'] = {
            'complete': title_found,
            'timestamp': status['stages'].get('published', {}).get('timestamp')
        }
    
    def _print_summary(self):
        """Print summary of pipeline status."""
        print("\n" + "="*80)
        print("📊 PODCAST PIPELINE STATUS")
        print("="*80)
        
        # Count by stage
        stage_counts = {stage: 0 for stage in self.STAGES}
        
        for ep_id, ep_data in self.status['episodes'].items():
            for stage in self.STAGES:
                if ep_data['stages'].get(stage, {}).get('complete'):
                    stage_counts[stage] += 1
        
        total = len(self.status['episodes'])
        
        print(f"\n📈 Pipeline Summary ({total} total episodes tracked):")
        print(f"  ✅ Downloaded:     {stage_counts['downloaded']:3d} / {total}")
        print(f"  ✅ Transcribed:    {stage_counts['transcribed']:3d} / {total}")
        print(f"  ✅ Analyzed:       {stage_counts['analyzed']:3d} / {total}")
        print(f"  ✅ Insight Created:{stage_counts['insight_created']:3d} / {total}")
        print(f"  ✅ Published:      {stage_counts['published']:3d} / {total}")
        
        # Show episodes stuck in each stage
        print("\n🔍 Episodes Needing Attention:")
        
        not_transcribed = []
        not_analyzed = []
        no_insight = []
        not_published = []
        
        for ep_id, ep_data in self.status['episodes'].items():
            info = ep_data['info']
            stages = ep_data['stages']
            
            if stages.get('downloaded', {}).get('complete') and not stages.get('transcribed', {}).get('complete'):
                not_transcribed.append(info['title'][:50])
            
            if stages.get('transcribed', {}).get('complete') and not stages.get('analyzed', {}).get('complete'):
                not_analyzed.append(info['title'][:50])
            
            if stages.get('analyzed', {}).get('complete') and not stages.get('insight_created', {}).get('complete'):
                no_insight.append(info['title'][:50])
            
            if stages.get('insight_created', {}).get('complete') and not stages.get('published', {}).get('complete'):
                not_published.append(info['title'][:50])
        
        if not_transcribed:
            print(f"\n  📝 Pending Transcription ({len(not_transcribed)}):")
            for title in not_transcribed:
                print(f"    - {title}")
        
        if not_analyzed:
            print(f"\n  🔬 Pending Analysis ({len(not_analyzed)}):")
            for title in not_analyzed:
                print(f"    - {title}")
        
        if no_insight:
            print(f"\n  💡 Pending Insight Creation ({len(no_insight)}):")
            for title in no_insight:
                print(f"    - {title}")
        
        if not_published:
            print(f"\n  🌐 Pending Publishing ({len(not_published)}):")
            for title in not_published:
                print(f"    - {title}")
        
        # Show complete episodes
        print("\n✅ Complete Episodes (All Stages):")
        complete_count = 0
        for ep_id, ep_data in self.status['episodes'].items():
            stages = ep_data['stages']
            if all(stages.get(s, {}).get('complete') for s in self.STAGES):
                print(f"    ✓ {ep_data['info']['title'][:50]}")
                complete_count += 1
        
        if complete_count == 0:
            print("    (None yet)")
        
        print(f"\n📅 Last Updated: {self.status['last_updated']}")
        print(f"📁 Status file: {STATUS_FILE}")
        print("="*80)
        
    def get_episodes_at_stage(self, stage: str) -> List[Dict]:
        """Get all episodes at a specific pipeline stage."""
        episodes = []
        for ep_id, ep_data in self.status['episodes'].items():
            if ep_data['stages'].get(stage, {}).get('complete'):
                episodes.append(ep_data['info'])
        return episodes
    
    def get_stuck_episodes(self) -> Dict[str, List[str]]:
        """Get episodes stuck at each stage."""
        stuck = {
            'downloaded': [],
            'transcribed': [],
            'analyzed': [],
            'insight_created': [],
            'published': []
        }
        
        for ep_id, ep_data in self.status['episodes'].items():
            info = ep_data['info']
            stages = ep_data['stages']
            
            # Find which stage it's stuck at
            for i, stage in enumerate(self.STAGES[:-1]):
                next_stage = self.STAGES[i + 1]
                if stages.get(stage, {}).get('complete') and not stages.get(next_stage, {}).get('complete'):
                    stuck[stage].append(info['title'])
                    break
        
        return stuck

def main():
    """Main entry point."""
    tracker = PodcastPipelineTracker()
    tracker.scan_pipeline()
    
    # Also save a detailed report
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    report_file = STATE_DIR / "pipeline_report.txt"
    with open(report_file, 'w') as f:
        f.write("Podcast Pipeline Report\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n\n")
        f.write(json.dumps(tracker.status, indent=2))
    
    print(f"\n📄 Detailed report saved to: {report_file}")

if __name__ == "__main__":
    main()
