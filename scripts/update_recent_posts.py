#!/usr/bin/env python3
"""
Update the Recent Posts section in site/index.html by pulling the latest tweets ingested via blogwatcher.

Usage:
    scripts/update_recent_posts.py [NUM]

NUM (optional): number of recent posts to include (default: 10)
"""
import subprocess
import re
import sys

# Configuration
NUM = int(sys.argv[1]) if len(sys.argv) > 1 else 10
INDEX_FILE = 'site/index.html'
START_MARKER = '<!-- RECENT_POSTS_START -->'
END_MARKER = '<!-- RECENT_POSTS_END -->'

# Fetch articles via blogwatcher
try:
    result = subprocess.run(['blogwatcher', 'articles', '--all'], check=True, stdout=subprocess.PIPE, text=True)
    output = result.stdout
except subprocess.CalledProcessError as e:
    print(f"Error running blogwatcher: {e}", file=sys.stderr)
    sys.exit(1)

# Split into article blocks (skip header)
blocks = output.strip().split('\n\n')[1:]
# Parse first NUM blocks
items = []
for block in blocks[:NUM]:
    lines = block.splitlines()
    title_line = lines[0].strip()
    url_line = next((l.strip() for l in lines if l.strip().startswith('URL: ')), None)
    if not url_line:
        continue
    url = url_line[len('URL: '):]
    m = re.match(r"\[\d+\]\s*(?:\[\w+\]\s*)?(.*)", title_line)
    title = m.group(1) if m else title_line
    items.append((title, url))

# Build replacement HTML
list_items = '\n'.join(f'      <li><a href="{url}">{title}</a></li>' for title, url in items)
replacement = (
    f"{START_MARKER}\n"
    "    <ul>\n"
    f"{list_items}\n"
    "    </ul>\n"
    f"{END_MARKER}"
)

# Read index file
with open(INDEX_FILE, 'r') as f:
    content = f.read()

# Replace section
pattern = re.compile(
    re.escape(START_MARKER) + r'.*?' + re.escape(END_MARKER),
    re.DOTALL
)
new_content = pattern.sub(replacement, content)

# Write back
with open(INDEX_FILE, 'w') as f:
    f.write(new_content)

print(f"Updated Recent Posts ({len(items)} items) in {INDEX_FILE}")
