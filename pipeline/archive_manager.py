#!/usr/bin/env python3
"""
Simple CLI for managing archive state of content.
Usage: python3 archive_manager.py <command> [options]
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db_manager import get_db

def list_content(item_type: str, show_archived: bool = False):
    """List content with IDs for archiving."""
    db = get_db()
    
    with db._get_connection() as conn:
        if item_type == 'insights':
            cursor = conn.execute("""
                SELECT id, title, source_name, source_date, display_on_main, archived_date
                FROM latest_insights
                ORDER BY source_date DESC
                LIMIT 20
            """)
            print(f"\n{'ID':<5} {'Date':<12} {'Status':<10} {'Title':<40} {'Source'}")
            print("-" * 100)
            for row in cursor.fetchall():
                status = "ARCHIVED" if not row['display_on_main'] else "ACTIVE"
                title = row['title'][:37] + "..." if len(row['title']) > 40 else row['title']
                date = row['source_date'][:10] if row['source_date'] else "Unknown"
                print(f"{row['id']:<5} {date:<12} {status:<10} {title:<40} {row['source_name']}")
        
        elif item_type == 'definitions':
            cursor = conn.execute("""
                SELECT id, term, added_date, display_on_main, vote_count
                FROM definitions
                ORDER BY vote_count DESC
            """)
            print(f"\n{'ID':<5} {'Added':<12} {'Status':<10} {'Votes':<6} {'Term'}")
            print("-" * 80)
            for row in cursor.fetchall():
                status = "ARCHIVED" if not row['display_on_main'] else "ACTIVE"
                date = row['added_date'] if row['added_date'] else "Unknown"
                print(f"{row['id']:<5} {date:<12} {status:<10} {row['vote_count']:<6} {row['term']}")
        
        elif item_type == 'overton':
            cursor = conn.execute("""
                SELECT id, term, first_detected_date, status, display_on_main, mention_count
                FROM overton_terms
                ORDER BY mention_count DESC
            """)
            print(f"\n{'ID':<5} {'First Seen':<12} {'Status':<12} {'Mentions':<9} {'Term'}")
            print("-" * 80)
            for row in cursor.fetchall():
                status = row['status'].upper() if not row['display_on_main'] else "ACTIVE"
                date = row['first_detected_date'] if row['first_detected_date'] else "Unknown"
                print(f"{row['id']:<5} {date:<12} {status:<12} {row['mention_count']:<9} {row['term']}")

def archive_item(item_type: str, item_id: int, reason: str):
    """Archive an item."""
    db = get_db()
    
    # Map plural to singular for db_manager
    type_map = {
        'insights': 'insight',
        'definitions': 'definition',
        'overton': 'overton'
    }
    
    db.archive_item(type_map.get(item_type, item_type), item_id, reason)
    print(f"✓ Archived {item_type[:-1]} ID {item_id}")
    print(f"  Reason: {reason}")

def restore_item(item_type: str, item_id: int):
    """Restore an archived item to main page."""
    db = get_db()
    
    table_map = {
        'insights': 'latest_insights',
        'definitions': 'definitions',
        'overton': 'overton_terms'
    }
    
    with db._get_connection() as conn:
        if item_type == 'overton':
            conn.execute(f"""
                UPDATE {table_map[item_type]}
                SET display_on_main = 1, status = 'active'
                WHERE id = ?
            """, (item_id,))
        else:
            conn.execute(f"""
                UPDATE {table_map[item_type]}
                SET display_on_main = 1
                WHERE id = ?
            """, (item_id,))
    
    print(f"✓ Restored {item_type[:-1]} ID {item_id} to main page")

def show_stats():
    """Show archive statistics."""
    db = get_db()
    
    with db._get_connection() as conn:
        print("\n" + "="*60)
        print("ARCHIVE STATISTICS")
        print("="*60)
        
        for table, name in [('latest_insights', 'Insights'), 
                           ('definitions', 'Definitions'), 
                           ('overton_terms', 'Overton Terms')]:
            cursor = conn.execute(f"""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN display_on_main = 1 THEN 1 ELSE 0 END) as active,
                    SUM(CASE WHEN display_on_main = 0 THEN 1 ELSE 0 END) as archived
                FROM {table}
            """)
            row = cursor.fetchone()
            print(f"\n{name}:")
            print(f"  Total: {row['total']}")
            print(f"  Active (main page): {row['active']}")
            print(f"  Archived: {row['archived']}")

def main():
    parser = argparse.ArgumentParser(description='Manage archive state of content')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List content')
    list_parser.add_argument('type', choices=['insights', 'definitions', 'overton'],
                           help='Type of content to list')
    list_parser.add_argument('--all', action='store_true',
                           help='Include archived items')
    
    # Archive command
    archive_parser = subparsers.add_parser('archive', help='Archive an item')
    archive_parser.add_argument('type', choices=['insights', 'definitions', 'overton'],
                              help='Type of content')
    archive_parser.add_argument('id', type=int, help='Item ID')
    archive_parser.add_argument('--reason', default='Manual archive',
                              help='Reason for archiving')
    
    # Restore command
    restore_parser = subparsers.add_parser('restore', help='Restore an archived item')
    restore_parser.add_argument('type', choices=['insights', 'definitions', 'overton'],
                              help='Type of content')
    restore_parser.add_argument('id', type=int, help='Item ID')
    
    # Stats command
    subparsers.add_parser('stats', help='Show archive statistics')
    
    args = parser.parse_args()
    
    if args.command == 'list':
        list_content(args.type, args.all)
    elif args.command == 'archive':
        archive_item(args.type, args.id, args.reason)
    elif args.command == 'restore':
        restore_item(args.type, args.id)
    elif args.command == 'stats':
        show_stats()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()