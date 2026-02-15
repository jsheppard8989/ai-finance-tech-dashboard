#!/usr/bin/env python3
"""
Email ingestion script for Gmail.
Connects via IMAP to fetch newsletter emails automatically.
"""

import os
import sys
import json
import re
import email
import imaplib
import ssl
from datetime import datetime
from pathlib import Path

# Config
EMAIL = "jsheppard8989@gmail.com"
PASSWORD = "blhv nutf osjs ocsm"  # App Password for 'Stock Pipeline'
IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993
TARGET_FOLDER = "NEWSLETTERS"  # Gmail label/folder to check

# Directories
INBOX_DIR = Path.home() / ".openclaw/workspace/pipeline/inbox"
PROCESSED_DIR = Path.home() / ".openclaw/workspace/pipeline/processed"

# Ensure directories exist
INBOX_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# Ticker extraction patterns
TICKER_PATTERN = re.compile(r'\$([A-Z]{1,5})\b|\b([A-Z]{2,5})\s+(?:stock|shares|ticker|symbol|nasdaq|nyse)', re.IGNORECASE)
COMPANY_TICKERS = {
    "nvidia": "NVDA", "nvidia": "NVDA",
    "apple": "AAPL",
    "microsoft": "MSFT",
    "tesla": "TSLA",
    "amazon": "AMZN",
    "google": "GOOGL", "alphabet": "GOOGL",
    "meta": "META", "facebook": "META",
    "bitcoin": "BTC", "microstrategy": "MSTR",
    "coinbase": "COIN",
}

def extract_tickers(text):
    """Extract potential stock tickers from text."""
    matches = TICKER_PATTERN.findall(text)
    tickers = [m[0] or m[1] for m in matches if m[0] or m[1]]
    
    # Also check for company name mentions
    text_lower = text.lower()
    for company, ticker in COMPANY_TICKERS.items():
        if company in text_lower and ticker not in tickers:
            tickers.append(ticker)
    
    return list(set(tickers))  # dedupe

def save_email(msg_data):
    """Save email with extracted metadata."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_subject = re.sub(r'[^\w\s-]', '', msg_data['subject'])[:50].strip()
    filename = f"{timestamp}_{safe_subject}.json"
    
    filepath = INBOX_DIR / filename
    with open(filepath, 'w') as f:
        json.dump(msg_data, f, indent=2)
    
    return filepath

def process_email(raw_email):
    """Parse raw email and extract relevant data."""
    msg = email.message_from_bytes(raw_email)
    
    subject = msg['subject'] or "No Subject"
    sender = msg['from'] or "Unknown"
    date = msg['date'] or datetime.now().isoformat()
    
    # Extract body
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    break
                except:
                    pass
            elif content_type == "text/html" and not body:
                try:
                    html = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    # Simple HTML tag stripping
                    body = re.sub(r'<[^>]+>', ' ', html)
                    body = re.sub(r'\s+', ' ', body)  # Normalize whitespace
                except:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
        except:
            body = str(msg.get_payload())
    
    # Extract tickers
    full_text = f"{subject} {body}"
    tickers = extract_tickers(full_text)
    
    return {
        "subject": subject,
        "sender": sender,
        "date": date,
        "content": body[:10000],  # Limit content size
        "content_preview": body[:500],
        "extracted_tickers": tickers,
        "ingested_at": datetime.now().isoformat()
    }

def fetch_via_gmail():
    """Fetch emails via Gmail IMAP."""
    print(f"Connecting to Gmail at {IMAP_SERVER}:{IMAP_PORT}...")
    
    try:
        # Create SSL context
        context = ssl.create_default_context()
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT, ssl_context=context)
        
        print(f"Logging in as {EMAIL}...")
        mail.login(EMAIL, PASSWORD)
        
        # Select target folder (NEWSLETTERS label in Gmail)
        print(f"Selecting folder: {TARGET_FOLDER}...")
        status, _ = mail.select(f'"{TARGET_FOLDER}"')
        if status != 'OK':
            print(f"⚠️  Folder '{TARGET_FOLDER}' not found, trying INBOX...")
            mail.select("inbox")
        
        # Search for unread emails
        _, search_data = mail.search(None, "UNSEEN")
        email_ids = search_data[0].split()
        
        print(f"Found {len(email_ids)} unread emails")
        
        processed = []
        for e_id in email_ids:
            try:
                _, data = mail.fetch(e_id, "(RFC822)")
                raw_email = data[0][1]
                
                msg_data = process_email(raw_email)
                filepath = save_email(msg_data)
                processed.append({
                    "file": str(filepath),
                    "subject": msg_data['subject'],
                    "tickers": msg_data['extracted_tickers']
                })
                
                # Mark as read (optional - keep unread if you want to see in Gmail too)
                # mail.store(e_id, '+FLAGS', '\\Seen')
                
            except Exception as e:
                print(f"Error processing email {e_id}: {e}")
        
        mail.close()
        mail.logout()
        
        return processed
        
    except imaplib.IMAP4.error as e:
        error_str = str(e)
        if "AUTHENTICATIONFAILED" in error_str:
            print("\n❌ Authentication failed.")
            print("   Gmail requires an 'App Password' if 2FA is enabled.")
            print("   1. Go to https://myaccount.google.com/apppasswords")
            print("   2. Generate an app password for 'Mail'")
            print("   3. Update the PASSWORD in this script")
        elif "Please log in via your web browser" in error_str:
            print("\n❌ Gmail security check required.")
            print("   1. Log into jsheppard8989@gmail.com in your browser")
            print("   2. Check for security alerts")
            print("   3. Enable 'Less secure app access' or use App Password")
        else:
            print(f"\n❌ IMAP Error: {e}")
        return []
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return []

def process_manual_files():
    """Process .eml files manually placed in inbox folder."""
    eml_files = list(INBOX_DIR.glob("*.eml"))
    
    if not eml_files:
        return []
    
    print(f"Found {len(eml_files)} .eml files to process")
    
    processed = []
    for eml_file in eml_files:
        try:
            with open(eml_file, 'rb') as f:
                raw_email = f.read()
            
            msg_data = process_email(raw_email)
            json_file = eml_file.with_suffix('.json')
            
            with open(json_file, 'w') as f:
                json.dump(msg_data, f, indent=2)
            
            # Move original to processed
            eml_file.rename(PROCESSED_DIR / eml_file.name)
            
            processed.append({
                "file": str(json_file),
                "subject": msg_data['subject'],
                "tickers": msg_data['extracted_tickers']
            })
        except Exception as e:
            print(f"Error processing {eml_file}: {e}")
    
    return processed

if __name__ == "__main__":
    print("=" * 50)
    print("Newsletter Ingestion Pipeline")
    print("=" * 50)
    
    # Check for manual mode flag
    manual_mode = "--manual" in sys.argv
    
    if manual_mode:
        print("\nRunning in MANUAL mode (processing .eml files)")
        results = process_manual_files()
    else:
        print("\nConnecting to Gmail...")
        results = fetch_via_gmail()
        
        if not results:
            print("\nNo emails fetched. Trying manual mode...")
            results = process_manual_files()
    
    print(f"\n✓ Processed {len(results)} emails")
    for r in results:
        tickers_str = ", ".join(r['tickers']) if r['tickers'] else "none"
        print(f"  - {r['subject'][:50]}... [tickers: {tickers_str}]")
    
    print(f"\nFiles saved to: {INBOX_DIR}")
    print(f"\nNext step: Run analysis to score stock mentions")
