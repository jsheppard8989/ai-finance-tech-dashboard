# ProtonMail Bridge Setup

## Installation

1. Download ProtonMail Bridge from: https://proton.me/mail/bridge
2. Install and open the app
3. Sign in with:
   - Email: gandolf2026@proton.me
   - Password: $ingul@rity2026!

## Configuration

Bridge exposes IMAP at `localhost:1143`

**Account Settings in Bridge:**
- IMAP Server: 127.0.0.1
- IMAP Port: 1143
- Username: gandolf2026@proton.me
- Password: [Bridge generates a separate IMAP password - get this from Bridge app]

## Testing

Once Bridge is running:
```bash
cd ~/.openclaw/workspace/pipeline
python3 ingest.py
```

The script will connect to Bridge and fetch unread emails.

## Keeping Bridge Running

- Bridge must be running to check email
- Set it to auto-start on login
- It runs in the background (menu bar on Mac)

## Manual Fallback

If Bridge has issues:
1. Export emails from ProtonMail web
2. Save .eml files to `~/.openclaw/workspace/pipeline/inbox/`
3. Run `python3 ingest.py --manual`
