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
import json as _json

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
        # Ensure we write the live in-memory structure (with reasons)
        with open(STATUS_FILE, 'w') as f:
            json.dump(self.status, f, indent=2)
    
    def scan_pipeline(self):
        """Scan all directories and database to update status."""
        print("🔍 Scanning podcast pipeline...\n")
        
        # 1. Get approved episodes from curation log
        approved_episodes = self._get_approved_episodes()
        if approved_episodes:
            # Only track approved episodes (fresh structure with reasons)
            self.status['episodes'] = {}
            for episode_id, episode_info in approved_episodes.items():
                self._update_episode_status(episode_id, episode_info)
        else:
            # No approved list: refresh all existing episodes so they get stage reasons
            for episode_id, data in list(self.status.get('episodes', {}).items()):
                info = data.get('info') or {}
                if info:
                    self._update_episode_status(episode_id, info)
        
        self._save_status()
        self._print_summary()
        
    def _get_approved_episodes(self) -> Dict:
        """Get list of approved episodes from curation log."""
        episodes = {}
        
        if not CURATION_LOG.exists():
            return episodes
            
        with open(CURATION_LOG, 'r') as f:
            log = json.load(f)
        
        from cutoff_date import is_before_cutoff
        for ep in log.get('episodes', []):
            if ep.get('status') != 'APPROVED':
                continue
            # Hard stop: do not track episodes before Feb 2026
            pub = ep.get('published_date') or (ep.get('published') or '')[:10]
            if pub and is_before_cutoff(pub):
                continue
            # Create unique ID from podcast + title
            ep_id = f"{ep['podcast']}_{ep['title'][:30]}".replace(' ', '_').lower()
            episodes[ep_id] = {
                'podcast': ep['podcast'],
                'title': ep['title'],
                # Prefer ISO date for display consistency (avoid raw RSS timestamps).
                'published': ep.get('published_date') or ep.get('published', 'Unknown'),
                'audio_file': ep.get('audio_file', ''),
                'keywords': ep.get('matched_keywords', []),
                'rss_guid': ep.get('rss_guid', '')
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
        downloaded_ok = Path(audio_file).exists() if audio_file else False
        
        # Stage 2: Transcribed?
        # Look for matching transcript file
        transcript_found = False
        transcript_file = None
        
        # Try to match transcript using strong signals only.
        # Avoid loose title-substring matching against transcript filename; it can create false positives.
        audio_filename = Path(audio_file).stem if audio_file else ''
        for transcript in TRANSCRIPT_DIR.glob('*.txt'):
            # Strong signal #1: transcript filename contains exact audio stem
            if audio_filename and audio_filename in transcript.name:
                transcript_found = True
                transcript_file = str(transcript)
                break

            # Strong signal #2: sidecar metadata matches podcast + title
            meta_path = transcript.with_suffix('.meta.json')
            if meta_path.exists():
                try:
                    with open(meta_path, 'r', encoding='utf-8') as mf:
                        meta = json.load(mf)
                    m_podcast = (meta.get('podcast_name') or '').strip().lower()
                    m_title = (meta.get('episode_title') or '').strip().lower()
                    e_podcast = (episode_info.get('podcast') or '').strip().lower()
                    e_title = (episode_info.get('title') or '').strip().lower()
                    podcast_match = bool(m_podcast and e_podcast and (m_podcast == e_podcast or m_podcast in e_podcast or e_podcast in m_podcast))
                    # Use a modest prefix check to avoid cross-episode collisions with generic names.
                    title_match = bool(m_title and e_title and (m_title[:36] == e_title[:36]))
                    if podcast_match and title_match:
                        transcript_found = True
                        transcript_file = str(transcript)
                        break
                except Exception:
                    pass
        
        # Logical consistency: if we have a transcript, we must have had audio at some point.
        if transcript_found and not downloaded_ok:
            downloaded_ok = True
        
        status['stages']['downloaded'] = {
            'complete': downloaded_ok,
            'timestamp': status['stages'].get('downloaded', {}).get('timestamp'),
            'reason': None if downloaded_ok else ('Audio file missing or not found' if not audio_file else 'Audio file path does not exist; re-run fetch.')
        }
        
        status['stages']['transcribed'] = {
            'complete': transcript_found,
            'file': transcript_file,
            'timestamp': status['stages'].get('transcribed', {}).get('timestamp'),
            'reason': None if transcript_found else ('Waiting for fetch/transcribe step' if downloaded_ok else 'No transcript until audio is downloaded.')
        }
        
        # Stage 3 & 4: Analyzed and in database?
        self._check_database_status(ep_id, episode_info, status)
        
        # Stage 5: Published?
        self._check_published_status(ep_id, episode_info, status)

        # Derive overall status enum from stages + reasons
        stage_reasons = {name: (status['stages'].get(name) or {}).get('reason') for name in self.STAGES}
        status['status'] = self._derive_status_enum(status['stages'], stage_reasons)
        
    def _normalize_name(self, name: str) -> str:
        """Normalize name for comparison."""
        return name.lower().replace(' ', '_').replace('-', '_')[:30]
    
    def _check_database_status(self, ep_id: str, episode_info: Dict, status: Dict):
        """Check if episode is in database."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        episode_row = None
        rss_guid = (episode_info.get('rss_guid') or '').strip()

        # Prefer GUID-based lookup when available (stable episode identity)
        if rss_guid:
            cursor.execute("""
                SELECT id, episode_date, summary
                FROM podcast_episodes
                WHERE rss_guid = ?
            """, (rss_guid,))
            episode_row = cursor.fetchone()

        # Fallback: podcast + title fuzzy match (for legacy rows without guid)
        if episode_row is None:
            cursor.execute("""
                SELECT id, episode_date, summary 
                FROM podcast_episodes 
                WHERE podcast_name LIKE ? AND episode_title LIKE ?
            """, (f"%{episode_info['podcast']}%", f"%{episode_info['title'][:40]}%"))
            episode_row = cursor.fetchone()

        analyzed_stage = status['stages'].get('analyzed') or {}
        analyzed_complete = episode_row is not None
        analyzed_reason = None

        if not analyzed_complete:
            # If analysis previously failed, surface that instead of a generic "waiting" message.
            failures_path = STATE_DIR / "analysis_failures.json"
            failure = None
            try:
                if failures_path.exists():
                    with open(failures_path, "r") as f:
                        failure_map = _json.load(f)
                    # Try to match by transcript stem from transcribed stage
                    t_stage = status['stages'].get('transcribed') or {}
                    t_file = t_stage.get('file') or ''
                    stem = Path(t_file).stem if t_file else ''
                    if stem and stem in failure_map:
                        failure = failure_map[stem]
            except Exception:
                failure = None

            if failure:
                code = failure.get("reason_code", "analysis_error")
                analyzed_reason = f"Analysis failed: {code}"
                # Tag this episode as blocked at the analysis stage
                status['status'] = 'blocked_analysis'
            else:
                analyzed_reason = 'Waiting for next analyze run (transcript → DB).'

        status['stages']['analyzed'] = {
            'complete': analyzed_complete,
            'episode_id': episode_row['id'] if episode_row else None,
            'timestamp': analyzed_stage.get('timestamp'),
            'reason': analyzed_reason,
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
                'timestamp': status['stages'].get('insight_created', {}).get('timestamp'),
                'reason': None if insight_row is not None else 'Insight not created yet (run pipeline / auto_pipeline).'
            }
        else:
            status['stages']['insight_created'] = {
                'complete': False,
                'timestamp': None,
                'reason': 'Depends on analyze step first.'
            }
        
        conn.close()
    
    def _check_published_status(self, ep_id: str, episode_info: Dict, status: Dict):
        """Check if episode is in the published data.js."""
        data_js = Path.home() / ".openclaw/workspace/site/data/data.js"
        
        if not data_js.exists():
            status['stages']['published'] = {'complete': False, 'reason': 'data.js not found (run export).'}
            return
        
        # Simple check - look for title in data.js
        with open(data_js, 'r', encoding='utf-8') as f:
            content = f.read()
        
        title_found = episode_info['title'][:30] in content
        
        status['stages']['published'] = {
            'complete': title_found,
            'timestamp': status['stages'].get('published', {}).get('timestamp'),
            'reason': None if title_found else 'Not in data.js yet (run export and push to site).'
        }

    def _derive_status_enum(self, stages: Dict, reasons: Dict[str, Optional[str]]) -> str:
        """
        Map per-stage booleans (and optionally reasons) to a single status string.
        Happy path:
          needs_download → needs_transcription → needs_analysis → needs_insight → needs_export → complete
        Blocked_* statuses can be added later when we classify hard failures.
        """
        st_flags = {k: bool((stages.get(k) or {}).get('complete')) for k in self.STAGES}

        # Inspect reasons for hard failures and return blocked_* statuses when needed
        analyzed_reason = reasons.get('analyzed') or ''
        if analyzed_reason.startswith('Analysis failed'):
            return 'blocked_analysis'

        if not st_flags.get('downloaded'):
            return 'needs_download'
        if not st_flags.get('transcribed'):
            return 'needs_transcription'
        if not st_flags.get('analyzed'):
            return 'needs_analysis'
        if not st_flags.get('insight_created'):
            return 'needs_insight'
        if not st_flags.get('published'):
            return 'needs_export'
        return 'complete'
    
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
