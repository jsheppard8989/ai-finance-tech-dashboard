# Security Policy

## Reporting Security Vulnerabilities

If you discover a security vulnerability, please report it responsibly:

1. **DO NOT** open a public GitHub issue
2. Contact the maintainer directly via [your preferred contact method]
3. Allow reasonable time for response before public disclosure

## Security Best Practices

### Credentials Management

- **NEVER** commit API keys, passwords, or tokens to GitHub
- Use environment variables (`.env` files)
- Rotate credentials immediately if accidentally exposed
- Use GitHub's secret scanning feature

### Environment Variables

Required environment variables:
```bash
GMAIL_USER=your-email@gmail.com
GMAIL_APP_PASSWORD=your-app-password
```

Set them via:
- `.env` file (automatically ignored by Git)
- GitHub Secrets (for Actions workflows)
- System environment variables

### Repository Security Features Enabled

- ✅ Secret scanning (detects leaked credentials)
- ✅ Dependency scanning
- ✅ CodeQL analysis

## Known Security Issues (Resolved)

### 2026-02-15: Hardcoded Gmail Password

**Status:** ✅ RESOLVED

**Description:** Gmail App Password was hardcoded in `pipeline/ingest.py`

**Impact:** Password visible in code history (now rotated)

**Fix:**
1. Password removed from source code
2. Now loaded from `GMAIL_APP_PASSWORD` environment variable
3. `.env.example` template provided
4. Runtime validation added
5. New password generated and old one revoked

**Action Required:** Users must set up their own `.env` file

---

## Dependencies

This project uses:
- Python 3.9+
- SQLite (local database)
- Gmail IMAP (with App Passwords)
- Optional: OpenAI API (for transcription)

Keep dependencies updated:
```bash
pip install --upgrade -r pipeline/requirements.txt
```