Entwicklungsprozess - während des Programmieren folgendes Script laufen lassen
/opt/mailfilter-venv/bin/python3 /opt/mailfilter-data/dev/watch_and_restart.py

systemctl start mailfilter-run.service
triggern – ideal z.B. für:
Schnelltests nach Modelltraining
händische Filterauslösung in Skripten oder Webhooks
später vielleicht sogar aus dem Webinterface 🧠
Wenn du magst, können wir auch eine kleine Web-Schaltfläche einbauen mit 📤 Jetzt filtern, die diesen Dienst per Flask aufruft. Interesse?

Logdatei									Zweck
logs/spam_filter.log						Zentrales Log für technische Fehler & Aktionen
logs/dietrich@2mail2.com/mailfilter.log		Pro Konto oder Benutzer, listet verschobene Mails mit Analysewerten; Verarbeitungsprotokoll je Mail – für Training, Kontrolle, Frontend
logs/mailfilter.error.logs					Nur Fehler pro Benutzer/E-Mail-Konto

Empfehlung für den Ordnernamen:
core → für Kernlogik & Funktionalität
utils → wenn’s nur Hilfsmethoden sind
helpers → auch gut, etwas lockerer
services → wenn du z.B. später REST-Logik einbaust

/opt/mailfilter-venv/bin/python3 /opt/mailfilter-data/spam_model_trainer.py
systemctl restart mailfilter-web.service
/opt/mailfilter-venv/bin/python3 /opt/mailfilter-data/app.py
/opt/mailfilter-venv/bin/python3 /opt/mailfilter-data/spam_filter.py #gibt den Fehler dann direkt aus, wenn restart nicht geht oder:
journalctl -u mailfilter-filter.service --since "30 min ago"
systemctl list-timers --all | grep mailfilter | awk '{print $NF}' | while read -r t; do echo "==== $t ===="; systemctl status "$t"; echo; done
sqlite3 /opt/mailfilter-data/mailfilter.db


# Mailfilter – systemd Dienste 
Dies dokumentiert alle systemd-Dienste und Timer, die im Zusammenhang mit dem Mailfilter-Projekt stehen.

## Aktive Dienste
| Dienstname               | Typ      | Aktiviert  | Status     | Beschreibung                                                                     |
|--------------------------|----------|------------|------------|----------------------------------------------------------------------------------|
| `mailfilter-idle`        | Service  | ✅         | 🟢 läuft   | IMAP IDLE Watcher, reagiert sofort auf neue Mails                                |
| `mailfilter-watch`       | Service  | ✅         | 🟢 läuft   | Änderung von Projektdateien Watcher, startet den mailfilter-web neu              |
| `mailfilter-web`         | Service  | ✅         | 🟢 läuft   | Webinterface auf Port 5000 (Flask)                                               |
| `mailfilter-train`       | Service  | ✅         | 💤 inaktiv | Trainings-Modul, wird täglich um 03:30 Uhr gestartet                             |
| `mailfilter-train.timer` | Timer    | ✅         | ⏳ wartet  | Führt täglich um 03:30 Uhr ein Spam-Training durch (via `spam_model_trainer.py`) |

## Deaktivierte bzw. ersetzte Dienste
| Dienstname               | Typ     | Aktiviert | Status  | Beschreibung                                                      |
|--------------------------|---------|-----------|---------|-------------------------------------------------------------------|
| `mailfilter-filter`      | Service | ❌        | ❌      | Ursprünglicher Filterdienst                                       |
| `mailfilter-filter.timer`| Timer   | ❌        | ❌      | Führte alle 15 Minuten den Filter aus, jetzt ersetzt durch `idle` |

## Weitere Dienste
| Dienstname         | Typ     | Beschreibung                                              |
|--------------------|---------|-----------------------------------------------------------|
| `mailfilter-run`   | Service | Manuelle Ausführung des Spamfilters über `spam_filter.py` |




.
├── app.py                      # Hauptprogramm (Flask)
├── auth.py                     # Login- & Account-Funktionen
├── create_user.py              # CLI-Tool zur Benutzeranlage
├── crypto.py                   # Fernet-Verschlüsselung
├── database.py                 # SQLite-Verbindung & Tabellendefinition
├── mailfilter.db               # SQLite-Datenbank
├── fernet.key                  # Schlüssel für verschlüsselte IMAP-Passwörter
├── templates/                  # HTML-Vorlagen
│   ├── base.html
│   ├── login.html
│   ├── inbox.html              # Zeigt Mails + Tabs für IMAP-Konten
│   └── accounts.html           # NEU: Verwaltung zusätzlicher E-Mail-Konten
├── models/
│   └── andi/                   # Spam-Modell pro Benutzer
│       ├── spam_model.pkl
│       └── spam_vectorizer.pkl
├── logs/
│   └── andi/                   # Logdateien pro Benutzer
│       ├── mailfilter.log
│       └── mailfilter.error.log


echo -e ".mode column\n.headers on\nSELECT * FROM users;" | sqlite3 /opt/mailfilter-data/mailfilter.db
sqlite3 /opt/mailfilter-data/mailfilter.db
.headers on;
.mode column;
SELECT * FROM users;
SELECT * FROM accounts;
.schema accounts  # => Ausgabe Datenbankstruktur
SELECT name FROM sqlite_master WHERE type='table';  # => Alle Tabellen
.quit
DELETE FROM mails;