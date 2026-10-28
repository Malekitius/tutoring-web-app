"""Installer checks use synthetic data and never touch the user's app."""

import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from unittest import TestCase, mock

import install


class InstallerTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "download"
        self.source.mkdir()
        for name in install.APP_ITEMS:
            item = self.source / name
            if "." in name:
                item.write_text(name, encoding="utf-8")
            else:
                item.mkdir()
                (item / "sample.py").write_text("pass\n", encoding="utf-8")
        self.source_data = self.source / "data"
        self.source_data.mkdir()
        with closing(sqlite3.connect(self.source_data / "db.sqlite3")) as database, database:
            database.execute("CREATE TABLE marker (value TEXT)")
            database.execute("INSERT INTO marker VALUES ('original')")
        (self.source_data / "assistant_auth.json").write_text("synthetic token", encoding="utf-8")
        (self.source_data / "uploads").mkdir()
        (self.source_data / "uploads" / "work.pdf").write_bytes(b"test work")

    def test_default_paths_for_macos_and_windows(self):
        home = self.root / "home"
        mac_app, mac_data = install.default_paths("darwin", home)
        self.assertEqual(mac_app, home / "Applications" / "TutorCabinet")
        self.assertEqual(mac_data, home / "Library" / "Application Support" / "TutorCabinet")
        win_app, win_data = install.default_paths("win32", home, self.root / "Local")
        self.assertEqual(win_app, self.root / "Local" / "TutorCabinet" / "app")
        self.assertEqual(win_data, self.root / "Local" / "TutorCabinet" / "data")

    def test_install_and_update_keep_database_outside_code(self):
        target, data = self.root / "installed", self.root / "personal-data"
        with mock.patch.object(install, "_port_busy", return_value=False), \
             mock.patch.object(install, "_create_environment"), \
             mock.patch.object(install, "_migrate"):
            install.install(self.source, target, data)
            self.assertFalse((target / "data").exists())
            self.assertEqual((data / "uploads" / "work.pdf").read_bytes(), b"test work")
            self.assertEqual((data / "assistant_auth.json").read_text(), "synthetic token")
            self.assertEqual(json.loads((target / "install-config.json").read_text())["data_dir"], str(data.resolve()))
            self.assertEqual(install.installed_data_dir(target), data.resolve())
            launcher = "Start Tutor Cabinet.bat" if sys.platform == "win32" else "Start Tutor Cabinet.command"
            self.assertTrue((target / launcher).exists())
            (self.source / "README.md").write_text("updated code", encoding="utf-8")
            install.install(self.source, target, data)
        self.assertEqual((target / "README.md").read_text(), "updated code")
        with closing(sqlite3.connect(data / "db.sqlite3")) as database:
            self.assertEqual(database.execute("SELECT value FROM marker").fetchone(), ("original",))
        self.assertEqual(len(list((data / "backups").glob("before-install-*.sqlite3"))), 2)
        with closing(sqlite3.connect(self.source_data / "db.sqlite3")) as database:
            self.assertEqual(database.execute("SELECT value FROM marker").fetchone(), ("original",))

    def test_update_rejects_changed_data_directory(self):
        target, data = self.root / "installed", self.root / "personal-data"
        with mock.patch.object(install, "_port_busy", return_value=False), \
             mock.patch.object(install, "_create_environment"), \
             mock.patch.object(install, "_migrate"):
            install.install(self.source, target, data)
            with self.assertRaisesRegex(RuntimeError, "другую папку данных"):
                install.install(self.source, target, self.root / "different-data")
        self.assertFalse((self.root / "different-data").exists())
        self.assertEqual(install.installed_data_dir(target), data.resolve())

    def test_unrelated_target_is_not_overwritten(self):
        target = self.root / "installed"
        target.mkdir()
        (target / "keep.txt").write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "не является установкой"):
            install.install(self.source, target, self.root / "personal-data")
        self.assertEqual((target / "keep.txt").read_text(), "keep")

    def test_windows_launcher_uses_installed_venv(self):
        target = self.root / "windows-app"
        target.mkdir()
        with mock.patch.object(install.sys, "platform", "win32"):
            install._write_launchers(target, self.root / "windows-data")
        launcher = (target / "Start Tutor Cabinet.bat").read_bytes()
        self.assertIn(b'.venv\\Scripts\\python.exe', launcher)
        self.assertIn(b'run_local.py', launcher)
        self.assertEqual(json.loads((target / "install-config.json").read_text())["format"], install.INSTALL_FORMAT)
