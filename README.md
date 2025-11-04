# CozyMail

Privater Web-Mailclient inkl. IMAP-IDLE, Spamfilter (ML), Logs und Webinterface.

## Features
- IMAP-IDLE Listener (`idle_mail_watcher.py`)
- Spamfilter-Training (`spam_model_trainer.py`)
- Web-UI (Flask) mit Inbox, Filtern, Logs, Accounts
- Pro Benutzer Modelle & Logs

## Schnellstart (Entwicklung)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env Werte anpassen
python app.py
