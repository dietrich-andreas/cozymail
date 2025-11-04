# watch_and_restart.py
import subprocess
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time
import os

WATCH_DIRS = ["/opt/mailfilter-data/core", "/opt/mailfilter-data", "/opt/mailfilter-data/templates"]

class ChangeHandler(FileSystemEventHandler):
    def on_any_event(self, event):
        if event.event_type in ("modified", "created", "deleted", "moved"):
            if event.src_path.endswith((".py", ".html", ".js")):
                print(f"[🔄] Änderung erkannt: {event.src_path}")
                restart_service()

def restart_service():
    try:
        subprocess.run(["systemctl", "restart", "mailfilter-web.service"], check=True)
        print("[✓] mailfilter-web.service erfolgreich neu gestartet")
    except subprocess.CalledProcessError as e:
        print(f"[!] Fehler beim Neustart: {e}")

if __name__ == "__main__":
    observer = Observer()
    handler = ChangeHandler()
    for d in WATCH_DIRS:
        if os.path.isdir(d):
            observer.schedule(handler, d, recursive=True)
    print("[👀] Beobachtung läuft...")
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
