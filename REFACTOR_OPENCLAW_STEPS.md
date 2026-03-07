# Exact .gitignore and git rm --cached for Openclaw/sensitive cleanup

Run all commands from the **workspace root**: `~/.openclaw/workspace`.

---

## 1. .gitignore (already applied)

The following was added to `.gitignore`:

```gitignore
# Openclaw & sensitive (do not commit to public repo)
AGENTS.md
SOUL.md
USER.md
IDENTITY.md
MEMORY.md
HEARTBEAT.md
TOOLS.md
memory/
bip39.txt
pending_contacts.json

# Pipeline state & inbox (optional: uncomment to stop committing these too)
# pipeline/state/
# pipeline/inbox/
```

To also stop committing pipeline state and inbox, uncomment the last two lines in `.gitignore`.

---

## 2. Stop tracking (files stay on disk)

**Required — Openclaw and clearly sensitive:**

```bash
git rm --cached AGENTS.md SOUL.md USER.md IDENTITY.md MEMORY.md HEARTBEAT.md TOOLS.md bip39.txt pending_contacts.json 2>/dev/null || true
git rm -r --cached memory/ 2>/dev/null || true
```

**Optional — pipeline state and inbox** (run if you uncommented those .gitignore lines):

```bash
git rm -r --cached pipeline/state/ 2>/dev/null || true
git rm -r --cached pipeline/inbox/ 2>/dev/null || true
```

**Then commit and push** (removes these paths from the remote; they remain in git history until you do history cleanup):

```bash
git add .gitignore
git commit -m "Stop tracking Openclaw and sensitive files; add to .gitignore"
git push origin main
```

---

## 3. Script alternative

Run the script instead of the commands above:

```bash
chmod +x scripts/untrack_sensitive.sh
./scripts/untrack_sensitive.sh
```

Then `git add .gitignore`, `git commit`, and `git push` as above. Edit the script to uncomment the optional pipeline block if you want to untrack `pipeline/state/` and `pipeline/inbox/` too.
