#!/usr/bin/env python3
"""Start the installed localhost app and open it in the default browser."""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


ADDRESS = "http://127.0.0.1:8765/"


def app_is_ready():
    try:
        with urllib.request.urlopen(ADDRESS, timeout=1) as response:
            return "Кабинет репетитора".encode("utf-8") in response.read(100_000)
    except (OSError, urllib.error.URLError):
        return False


def open_when_ready():
    for _ in range(80):
        if app_is_ready():
            webbrowser.open(ADDRESS)
            return
        time.sleep(0.25)


def main():
    root = Path(__file__).resolve().parent
    config = json.loads((root / "install-config.json").read_text(encoding="utf-8"))
    if config.get("format") != "tutoring-web-app.install":
        raise RuntimeError("Неверная конфигурация установки")
    os.environ["TUTOR_DATA_DIR"] = config["data_dir"]
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    if app_is_ready():
        webbrowser.open(ADDRESS)
        print("Приложение уже работает. Открываю его в браузере.")
        return
    threading.Thread(target=open_when_ready, daemon=True).start()
    os.chdir(root)
    from django.core.management import execute_from_command_line
    execute_from_command_line(["manage.py", "runserver", "127.0.0.1:8765", "--noreload"])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Не удалось запустить приложение: {exc}", file=sys.stderr)
        sys.exit(1)
