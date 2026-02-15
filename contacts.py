#!/usr/bin/env python3
"""
Contact form backend handler
Processes submissions, sends verification messages, and stores verified contacts
"""

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

# Paths
WORKSPACE = Path.home() / ".openclaw/workspace"
CONTACTS_FILE = WORKSPACE / "contacts.json"
PENDING_FILE = WORKSPACE / "pending_contacts.json"
LOG_FILE = WORKSPACE / "contact_log.txt"

def log(message):
    """Log with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    print(entry)
    with open(LOG_FILE, 'a') as f:
        f.write(entry + '\n')

def load_contacts():
    """Load verified contacts"""
    if CONTACTS_FILE.exists():
        with open(CONTACTS_FILE, 'r') as f:
            return json.load(f)
    return {"contacts": [], "lastUpdated": None}

def save_contacts(data):
    """Save verified contacts"""
    data["lastUpdated"] = datetime.now().isoformat()
    with open(CONTACTS_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def is_valid_email(email):
    """Validate email format"""
    pattern = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
    return re.match(pattern, email) is not None

def is_valid_phone(phone):
    """Validate phone format"""
    # Remove spaces and common separators
    cleaned = re.sub(r'[\s\-\(\)\.]', '', phone)
    # Check for valid phone pattern (with optional + and country code)
    pattern = r'^[\+]?[1]?[0-9]{10,15}$'
    return re.match(pattern, cleaned) is not None

def detect_contact_type(contact):
    """Detect if contact is email or phone"""
    if '@' in contact and is_valid_email(contact):
        return 'email'
    elif is_valid_phone(contact):
        return 'phone'
    return None

def send_verification_email(email, name, code):
    """Send verification email - placeholder for actual implementation"""
    log(f"Would send verification email to: {email}")
    # In production, integrate with SendGrid, AWS SES, etc.
    # For now, create a script that can be run manually
    script = WORKSPACE / "send_verification_email.sh"
    with open(script, 'w') as f:
        f.write(f'''#!/bin/bash
# Verification email for {name} ({email})
# Verification code: {code}

echo "Verification code for {name}: {code}"
echo "Send this via your preferred email method"
''')
    os.chmod(script, 0o755)
    return True

def send_verification_sms(phone, name, code):
    """Send verification SMS via iMessage"""
    log(f"Sending verification SMS to: {phone}")
    # Clean the phone number
    cleaned = re.sub(r'[\s\-\(\)\.]', '', phone)
    if not cleaned.startswith('+'):
        cleaned = '+1' + cleaned  # Assume US if no country code
    
    message = f"Hi {name or 'there'}! Your 6AIndolf verification code is: {code}. Reply with this code to confirm."
    
    # Use the iMessage send script
    imsg_script = WORKSPACE / "send_imessage.sh"
    if imsg_script.exists():
        import subprocess
        result = subprocess.run(
            [str(imsg_script), cleaned, message],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            log(f"Verification SMS sent successfully to {cleaned}")
            return True
        else:
            log(f"Failed to send SMS: {result.stderr}")
            return False
    else:
        log(f"iMessage script not found at {imsg_script}")
        return False

def generate_verification_code():
    """Generate 6-digit verification code"""
    import random
    return ''.join([str(random.randint(0, 9)) for _ in range(6)])

def process_new_submission(name, contact, message):
    """Process a new contact submission"""
    log(f"Processing new submission: {name} ({contact})")
    
    contact_type = detect_contact_type(contact)
    if not contact_type:
        log(f"Invalid contact format: {contact}")
        return False
    
    contacts = load_contacts()
    
    # Check if already exists
    for existing in contacts["contacts"]:
        if existing["contact"] == contact:
            log(f"Contact already exists: {contact}")
            return False
    
    # Generate verification code
    code = generate_verification_code()
    
    # Create pending contact entry
    pending = {
        "id": int(time.time()),
        "name": name or "Anonymous",
        "contact": contact,
        "contactType": contact_type,
        "message": message or "",
        "submittedAt": datetime.now().isoformat(),
        "verificationCode": code,
        "verified": False,
        "attempts": 0
    }
    
    # Send verification
    if contact_type == 'email':
        success = send_verification_email(contact, name, code)
    else:
        success = send_verification_sms(contact, name, code)
    
    if success:
        # Save to pending
        pending_data = {"pending": []}
        if PENDING_FILE.exists():
            with open(PENDING_FILE, 'r') as f:
                pending_data = json.load(f)
        
        pending_data["pending"].append(pending)
        with open(PENDING_FILE, 'w') as f:
            json.dump(pending_data, f, indent=2)
        
        log(f"Verification sent to {contact}. Code: {code}")
        return True
    
    return False

def verify_contact(contact, code):
    """Verify a contact with their code"""
    log(f"Attempting verification for {contact} with code {code}")
    
    if not PENDING_FILE.exists():
        log("No pending contacts file")
        return False
    
    with open(PENDING_FILE, 'r') as f:
        pending_data = json.load(f)
    
    for pending in pending_data.get("pending", []):
        if pending["contact"] == contact:
            if pending["verificationCode"] == code:
                # Move to verified contacts
                contacts = load_contacts()
                verified_contact = {
                    "id": pending["id"],
                    "name": pending["name"],
                    "contact": pending["contact"],
                    "contactType": pending["contactType"],
                    "message": pending["message"],
                    "submittedAt": pending["submittedAt"],
                    "verifiedAt": datetime.now().isoformat(),
                    "verified": True,
                    "weeklyUpdates": None  # None = asked but no response yet, True = subscribed, False = declined
                }
                contacts["contacts"].append(verified_contact)
                save_contacts(contacts)
                
                # Remove from pending
                pending_data["pending"] = [p for p in pending_data["pending"] if p["contact"] != contact]
                with open(PENDING_FILE, 'w') as f:
                    json.dump(pending_data, f, indent=2)
                
                log(f"✓ Contact verified: {contact}")
                
                # Send welcome message
                send_welcome_message(verified_contact)
                return True
            else:
                pending["attempts"] += 1
                with open(PENDING_FILE, 'w') as f:
                    json.dump(pending_data, f, indent=2)
                log(f"Invalid code for {contact}. Attempt {pending['attempts']}")
                return False
    
    log(f"No pending contact found: {contact}")
    return False

def send_welcome_message(contact):
    """Send welcome message to newly verified contact"""
    name = contact["name"]
    contact_info = contact["contact"]
    contact_type = contact["contactType"]
    
    message = f"Welcome{name and ' ' + name or ''}! 🧙‍♂️ You've been added to the 6AIndolf network. Would you like a once-weekly update of our latest insights? Reply YES to subscribe or STOP anytime to unsubscribe."
    
    if contact_type == 'phone':
        imsg_script = WORKSPACE / "send_imessage.sh"
        if imsg_script.exists():
            import subprocess
            cleaned = re.sub(r'[\s\-\(\)\.]', '', contact_info)
            if not cleaned.startswith('+'):
                cleaned = '+1' + cleaned
            subprocess.run([str(imsg_script), cleaned, message])
            log(f"Welcome message sent to {contact_info}")
    else:
        log(f"Would send welcome email to {contact_info}")

def update_preference(contact, wants_updates):
    """Update weekly update preference for a contact"""
    contacts = load_contacts()
    
    for c in contacts["contacts"]:
        if c["contact"] == contact:
            c["weeklyUpdates"] = wants_updates
            c["preferenceUpdatedAt"] = datetime.now().isoformat()
            save_contacts(contacts)
            
            status = "subscribed" if wants_updates else "unsubscribed"
            log(f"Contact {contact} {status} from weekly updates")
            
            # Send confirmation
            name = c["name"]
            contact_type = c["contactType"]
            contact_info = c["contact"]
            
            if wants_updates:
                message = f"✓ You're now subscribed to weekly updates from 6AIndolf! Expect insights every Sunday. Reply STOP anytime to unsubscribe."
            else:
                message = f"✓ You've been unsubscribed from weekly updates. You can reply YES anytime to resubscribe."
            
            if contact_type == 'phone':
                imsg_script = WORKSPACE / "send_imessage.sh"
                if imsg_script.exists():
                    import subprocess
                    cleaned = re.sub(r'[\s\-\(\)\.]', '', contact_info)
                    if not cleaned.startswith('+'):
                        cleaned = '+1' + cleaned
                    subprocess.run([str(imsg_script), cleaned, message])
                    log(f"Confirmation sent to {contact_info}")
            else:
                log(f"Would send confirmation email to {contact_info}")
            
            return True
    
    log(f"Contact not found: {contact}")
    return False

def list_contacts():
    """List all contacts"""
    contacts = load_contacts()
    print(f"\nVerified Contacts ({len(contacts['contacts'])}):")
    print("-" * 70)
    print(f"  {'Name':<20} | {'Contact':<25} | {'Weekly?':<8} | {'Verified':<10}")
    print("-" * 70)
    for c in contacts["contacts"]:
        weekly_status = "?" if c.get('weeklyUpdates') is None else ("YES" if c.get('weeklyUpdates') else "NO")
        print(f"  {c['name']:<20} | {c['contact']:<25} | {weekly_status:<8} | {c['verifiedAt'][:10]}")
    
    if PENDING_FILE.exists():
        with open(PENDING_FILE, 'r') as f:
            pending_data = json.load(f)
        pending = pending_data.get("pending", [])
        if pending:
            print(f"\nPending Verification ({len(pending)}):")
            print("-" * 60)
            for p in pending:
                print(f"  {p['name']} | {p['contact']} | Code: {p['verificationCode']} | Submitted: {p['submittedAt'][:10]}")

def main():
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python3 contacts.py <command> [args]")
        print("")
        print("Commands:")
        print("  add <name> <contact> [message]  - Add new contact")
        print("  verify <contact> <code>          - Verify a contact")
        print("  subscribe <contact>              - Subscribe to weekly updates")
        print("  unsubscribe <contact>            - Unsubscribe from weekly updates")
        print("  list                             - List all contacts")
        print("")
        print("Examples:")
        print('  python3 contacts.py add "John Doe" "john@example.com" "Interested in AI stocks"')
        print('  python3 contacts.py add "Jane" "+1-555-123-4567" "Crypto investor"')
        print('  python3 contacts.py verify "john@example.com" 123456')
        print('  python3 contacts.py subscribe "john@example.com"')
        print('  python3 contacts.py unsubscribe "+1-555-123-4567"')
        return
    
    command = sys.argv[1]
    
    if command == "add":
        if len(sys.argv) < 4:
            print("Usage: python3 contacts.py add <name> <contact> [message]")
            return
        name = sys.argv[2]
        contact = sys.argv[3]
        message = sys.argv[4] if len(sys.argv) > 4 else ""
        process_new_submission(name, contact, message)
    
    elif command == "verify":
        if len(sys.argv) < 4:
            print("Usage: python3 contacts.py verify <contact> <code>")
            return
        contact = sys.argv[2]
        code = sys.argv[3]
        if verify_contact(contact, code):
            print(f"✓ {contact} verified successfully!")
        else:
            print(f"✗ Verification failed for {contact}")
    
    elif command == "subscribe" or command == "yes":
        if len(sys.argv) < 3:
            print("Usage: python3 contacts.py subscribe <contact>")
            return
        contact = sys.argv[2]
        if update_preference(contact, True):
            print(f"✓ {contact} subscribed to weekly updates!")
        else:
            print(f"✗ Could not subscribe {contact}")
    
    elif command == "unsubscribe" or command == "stop":
        if len(sys.argv) < 3:
            print("Usage: python3 contacts.py unsubscribe <contact>")
            return
        contact = sys.argv[2]
        if update_preference(contact, False):
            print(f"✓ {contact} unsubscribed from weekly updates.")
        else:
            print(f"✗ Could not unsubscribe {contact}")
    
    elif command == "list":
        list_contacts()
    
    else:
        print(f"Unknown command: {command}")

if __name__ == "__main__":
    main()
