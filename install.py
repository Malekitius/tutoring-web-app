#!/usr/bin/env python3
"""Install the local tutor app without putting personal data inside the code folder."""

import argparse
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import uuid
import venv
from contextlib import closing
from datetime import datetime
from pathlib import Path


APP_ITEMS = (
    "assistant", "assignments", "config", "finances", "schedule", "students",
    "static", "docs", "manage.py", "run_local.py", "requirements.txt", "README.md",
)
SKIP_NAMES = {"__pycache__", ".DS_Store", "*.pyc", "*.pyo"}
INSTALL_FORMAT = "tutoring-web-app.install"


def default_paths(system=None, home=None, localappdata=None):
    system = system or sys.platform
    home = Path(home or Path.home())
    if system == "darwin":
        return home / "Applications" / "TutorCabinet", home / "Library" / "Application Support" / "TutorCabinet"
    if system == "win32":
        base = Path(localappdata or os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "TutorCabinet"
        return base / "app", base / "data"
    raise RuntimeError("Установщик пока поддерживает macOS и Windows")


def installed_data_dir(target):
    config_file = target / "install-config.json"
    if not config_file.is_file():
        raise RuntimeError(f"Папка {target} уже существует и не является установкой приложения")
    try:
        configuration = json.loads(config_file.read_text(encoding="utf-8"))
        if configuration.get("format") != INSTALL_FORMAT or not isinstance(configuration.get("data_dir"), str):
            raise ValueError
        return Path(configuration["data_dir"]).expanduser().resolve()
    except (OSError, ValueError, TypeError):
        raise RuntimeError("Не удалось прочитать настройки существующей установки") from None


def python_in(venv_dir):
    return venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _port_busy(port=8765):
    with socket.socket() as connection:
        connection.settimeout(0.2)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def _copy_application(source, staging):
    for name in APP_ITEMS:
        item = source / name
        if not item.exists():
            raise RuntimeError(f"В скачанном архиве нет {name}")
        destination = staging / name
        if item.is_dir():
            shutil.copytree(item, destination, ignore=shutil.ignore_patterns(*SKIP_NAMES))
        else:
            shutil.copy2(item, destination)


def _create_environment(staging):
    venv.EnvBuilder(with_pip=True).create(staging / ".venv")
    subprocess.run([
        str(python_in(staging / ".venv")), "-m", "pip", "install", "--disable-pip-version-check",
        "-r", str(staging / "requirements.txt"),
    ], check=True)


def _copy_existing_data(source, data_dir):
    source_data = source / "data"
    if (data_dir / "db.sqlite3").exists() or not (source_data / "db.sqlite3").is_file():
        data_dir.mkdir(parents=True, exist_ok=True)
        return False
    data_dir.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source_data / "db.sqlite3")) as original, closing(sqlite3.connect(data_dir / "db.sqlite3")) as copy:
        original.backup(copy)
    if (source_data / "assistant_auth.json").is_file() and not (data_dir / "assistant_auth.json").exists():
        shutil.copy2(source_data / "assistant_auth.json", data_dir / "assistant_auth.json")
    for name in ("uploads", "backups"):
        if (source_data / name).is_dir() and not (data_dir / name).exists():
            shutil.copytree(source_data / name, data_dir / name)
    return True


def _backup_database(data_dir):
    database = data_dir / "db.sqlite3"
    if not database.is_file():
        return None
    backups = data_dir / "backups"
    backups.mkdir(exist_ok=True)
    backup = backups / f"before-install-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.sqlite3"
    with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    return backup


def _secure_data(data_dir):
    if sys.platform == "win32":
        return
    data_dir.chmod(0o700)
    for item in data_dir.rglob("*"):
        if item.is_symlink():
            continue
        item.chmod(0o700 if item.is_dir() else 0o600)


def _migrate(staging, data_dir):
    env = os.environ.copy()
    env["TUTOR_DATA_DIR"] = str(data_dir)
    subprocess.run([str(python_in(staging / ".venv")), "manage.py", "migrate", "--noinput"],
                   cwd=staging, env=env, check=True)


def _write_launchers(staging, data_dir):
    (staging / "install-config.json").write_text(json.dumps({
        "format": INSTALL_FORMAT, "data_dir": str(data_dir),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if sys.platform == "win32":
        (staging / "Start Tutor Cabinet.bat").write_bytes(
            b'@echo off\r\nchcp 65001 >nul\r\nset "PYTHONIOENCODING=utf-8"\r\ncd /d "%~dp0"\r\n".venv\\Scripts\\python.exe" run_local.py\r\nif errorlevel 1 pause\r\n'
        )
    else:
        launcher = staging / "Start Tutor Cabinet.command"
        launcher.write_text('#!/bin/sh\ncd "$(dirname "$0")" || exit 1\nexec .venv/bin/python run_local.py\n', encoding="utf-8")
        launcher.chmod(0o755)


def install(source, target, data_dir):
    source, target, data_dir = (Path(path).expanduser().resolve() for path in (source, target, data_dir))
    if source == target or data_dir.is_relative_to(target):
        raise RuntimeError("Папка установки и папка данных должны быть отдельно от скачанного архива")
    if target.exists() and installed_data_dir(target) != data_dir:
        raise RuntimeError("Уже установленное приложение использует другую папку данных; путь нельзя менять при обновлении")
    if _port_busy() and ((source / "data" / "db.sqlite3").exists() or (data_dir / "db.sqlite3").exists()):
        raise RuntimeError("Закройте работающее приложение перед установкой, затем запустите установщик снова")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".tutor-install-", dir=target.parent))
    old_target = target.parent / f".{target.name}-previous-{uuid.uuid4().hex[:8]}"
    backup = None
    moved_old = False
    try:
        print("Копирование приложения…", flush=True)
        _copy_application(source, staging)
        print("Создание окружения Python и установка зависимостей…", flush=True)
        _create_environment(staging)
        imported = _copy_existing_data(source, data_dir)
        backup = _backup_database(data_dir)
        _secure_data(data_dir)
        print("Обновление структуры базы данных…", flush=True)
        _migrate(staging, data_dir)
        _write_launchers(staging, data_dir)
        if target.exists():
            target.rename(old_target)
            moved_old = True
        try:
            staging.rename(target)
        except Exception:
            if moved_old:
                old_target.rename(target)
                moved_old = False
            raise
        if moved_old:
            shutil.rmtree(old_target, ignore_errors=True)
        print(f"Готово. Приложение: {target}")
        print(f"Данные: {data_dir}")
        if imported:
            print("Существующая база, загруженные работы и подключение помощника скопированы из старой папки data.")
        if backup:
            print(f"Копия базы перед установкой: {backup}")
        launcher = "Start Tutor Cabinet.bat" if sys.platform == "win32" else "Start Tutor Cabinet.command"
        print(f"Откройте файл «{launcher}» в папке приложения.")
        return target
    except Exception:
        if backup and backup.exists():
            with closing(sqlite3.connect(backup)) as original, closing(sqlite3.connect(data_dir / "db.sqlite3")) as current:
                original.backup(current)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def main():
    if sys.version_info < (3, 11):
        raise RuntimeError("Нужен Python 3.11 или новее")
    parser = argparse.ArgumentParser(description="Установить локальный кабинет репетитора")
    parser.add_argument("--target", type=Path, help="Папка программы (необязательно)")
    parser.add_argument("--data", type=Path, help="Папка личных данных (необязательно)")
    args = parser.parse_args()
    default_target, default_data = default_paths()
    target = (args.target or default_target).expanduser().resolve()
    data_dir = args.data or (installed_data_dir(target) if target.exists() else default_data)
    install(Path(__file__).resolve().parent, target, data_dir)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Ошибка установки: {exc}", file=sys.stderr)
        sys.exit(1)
