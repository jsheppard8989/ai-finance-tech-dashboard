# Prompt log (encrypted)

`jared_prompts.enc` is **AES-256-CBC** (OpenSSL, PBKDF2). Your passphrase is **not** stored in this repo.

## Decrypt (read the log)

```bash
cd "$(dirname "$0")"
openssl enc -d -aes-256-cbc -pbkdf2 -in jared_prompts.enc -out jared_prompts.plain.txt
# Enter your passphrase when prompted. Then:
open jared_prompts.plain.txt   # or cat / less
```

## Encrypt after editing plaintext

```bash
openssl enc -aes-256-cbc -salt -pbkdf2 -in jared_prompts.plain.txt -out jared_prompts.enc
# Enter passphrase when prompted
rm jared_prompts.plain.txt   # optional: remove plaintext when done
```

## Security note

Anyone with the **file** and the **passphrase** can read it. Don’t commit `jared_prompts.plain.txt` (it is gitignored). Rotating the passphrase means re-encrypting with a new one.

## Maintenance

Tim appends to this log when you ask to log a session or a prompt. History before the log existed cannot be recovered from chat logs automatically.
