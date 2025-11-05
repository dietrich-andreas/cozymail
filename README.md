# 📬 CozyMail

**CozyMail** ist ein selbst-gehosteter, intelligenter Mail-Filter mit moderner Web-Oberfläche.
Er kombiniert IMAP-Abruf, Spam-Erkennung mittels Machine-Learning und komfortables UI auf Basis von **Flask** und **Bulma**.

---

## 🚀 Features

* 📥 **Multi-Account-IMAP-Support** – mehrere Postfächer gleichzeitig verwalten
* 🔥 **Spam- und Ham-Training** mit `spam_model.pkl` und `vectorizer.pkl`
* ✅ **Whitelist- / Blacklist-Verwaltung** direkt aus der Web-Oberfläche
* 🔄 **Live-Updates** via Socket.IO (neue Mails erscheinen sofort)
* 🧠 **SQLite-Datenbank-Backend** – leichtgewichtig und zuverlässig
* 🧩 **Flask-basierte Web-UI** mit responsive Design und moderner Struktur
* 🧾 **Trainings- und Filter-Logs** zur Modell-Analyse

---

## 🏗 Projektstruktur

```text
cozymail/
├── app.py                # Haupt-Flask-Anwendung
├── core/                 # Logik und Datenbank-Handling
│   ├── create_database.py
│   ├── auth.py
│   ├── logger.py
│   └── ...
├── templates/            # Jinja2-Vorlagen für die Web-UI
│   ├── inbox.html
│   └── base.html
├── static/               # Statische Dateien (CSS, JS, Icons)
├── idle_mail_watcher.py  # Hintergrund-Watcher-Service
├── spam_filter.py        # Mail-Klassifizierung
├── spam_model_trainer.py # Training der ML-Modelle
├── model_utils.py        # Hilfsfunktionen für ML
├── create_user.py        # CLI-Tool zur Nutzeranlage
├── requirements.txt      # Python-Abhängigkeiten
└── .env.example          # Beispiel-Konfiguration
```

---

## ⚙️ Installation & Start

### 🔧 Voraussetzungen

* Python ≥ 3.11
* IMAP-Zugangsdaten deiner Mailkonten
* Linux-System (empfohlen Ubuntu 22.04 LTS / Proxmox-LXC)

### 💡 Setup-Schritte

```bash
# 1. Repository klonen
git clone https://github.com/dietrich-andreas/cozymail.git
cd cozymail

# 2. Virtuelle Umgebung erstellen
python3 -m venv venv
source venv/bin/activate

# 3. Abhängigkeiten installieren
pip install -r requirements.txt

# 4. Konfigurationsdatei anlegen
cp .env.example .env
# .env nach Bedarf anpassen (IMAP-Server, Benutzer, Passwörter etc.)

# 5. Datenbank erzeugen
python3 -m core.create_database

# 6. Web-App starten
python3 app.py
```

Anschließend kannst du **CozyMail** im Browser öffnen:
👉 [http://localhost:5000](http://localhost:5000)

---

## 🧠 Machine-Learning

CozyMail nutzt ein trainiertes Modell (`spam_model.pkl`) mit einem Vektorisierer (`vectorizer.pkl`) zur Erkennung von Spam.
Beide können über das Script `spam_model_trainer.py` neu trainiert werden.

```bash
python3 spam_model_trainer.py
```

Das Modell wird mit neuen Mails kontinuierlich verbessert – jede Spam-Markierung oder Whitelist-Aktion fließt in das Training ein.

---

## 🧩 System-Dienste

CozyMail kann über Systemd-Dienste automatisch laufen, z. B.:

* `mailfilter-web.service` → Flask-Webserver
* `mailfilter-filter.service` → Hintergrund-Watcher (Idle-IMAP)

Diese Services befinden sich in `/etc/systemd/system/` und werden beim Boot gestartet.

---

## 📁 Verzeichnisbeschreibungen

| Ordner       | Inhalt                                  |
| :----------- | :-------------------------------------- |
| `core/`      | Zentrale Logik: DB, Auth, ML-Funktionen |
| `templates/` | HTML-Vorlagen (Bulma-UI)                |
| `static/`    | CSS, JS, Bilder                         |
| `dev/`       | Entwicklungs- und Testscripts           |

---

## 🧑‍💻 Autor & Kontakt

**Andreas Dietrich**
🌐 cozyhub.eu
📧 [dietrich@cozyhub.eu](mailto:dietrich@cozyhub.eu)

---

## 🪪 Lizenz

Dieses Projekt ist unter der **MIT-Lizenz** veröffentlicht.
Siehe `LICENSE` für Details.

---

## ⭐️ Support

Wenn dir **CozyMail** gefällt, lass dem Projekt gern ein ⭐️ auf GitHub da
oder teile dein Feedback über Issues oder Pull Requests!
