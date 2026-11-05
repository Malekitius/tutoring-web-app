"""Exercise the accounts configuration against fresh, separate databases."""

import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase


class CabinetPilotTests(SimpleTestCase):
    def test_two_teachers_have_separate_records_files_and_backup_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            self.run_cabinet_check(directory)

    def test_postgres_cabinets_and_import_of_a_sqlite_archive(self):
        maintenance_db = os.environ.get("TUTOR_TEST_POSTGRES_DB")
        if not maintenance_db:
            self.skipTest("Set TUTOR_TEST_POSTGRES_DB to run the local PostgreSQL integration test.")
        import psycopg
        from psycopg import sql

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "sqlite.zip"
            self.run_cabinet_check(root / "sqlite", "--export", str(archive))
            database = "tutor_test_" + secrets.token_hex(8)
            with psycopg.connect(dbname=maintenance_db, host=os.environ.get("PGHOST", "127.0.0.1"),
                                 autocommit=True) as connection:
                connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
                try:
                    self.run_cabinet_check(root / "postgres", "--import", str(archive), database=database)
                finally:
                    connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))

    def run_cabinet_check(self, directory, *args, database=""):
        result = subprocess.run(
            [sys.executable, "-m", "config.test_cabinets", *args],
            env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings",
                 "TUTOR_DATA_DIR": str(directory), "TUTOR_ACCOUNTS": "1", "TUTOR_POSTGRES_DB": database,
                 "TUTOR_SECRET_KEY": secrets.token_urlsafe(48), "PYTHONIOENCODING": "utf-8"},
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def check_cabinet_isolation(export_path=None, import_path=None):
    """Run in a fresh process so the test runner's legacy DB stays untouched."""
    import io
    import json
    import zipfile
    from unittest.mock import patch

    import django
    from PIL import Image
    from pypdf import PdfWriter

    django.setup()
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.core.management import call_command
    from django.db import connection, connections
    from django.test import Client

    from assignments.models import Exercise, ExerciseGrade, Submission, TaskFigure, Worksheet
    from assistant.chatgpt_auth import auth_path
    from config.cabinets import cabinet_scope, cabinet_directory
    from finances.models import Payment
    from materials.models import Material, MaterialPage
    from school.models import SchoolClass
    from students.models import Student

    call_command("migrate", verbosity=0)
    password = "Local-Test-" + secrets.token_urlsafe(16)
    users = get_user_model()
    for username in ("teacher_one", "teacher_two"):
        with patch("students.management.commands.create_cabinet.getpass", return_value=password):
            call_command("create_cabinet", username)
    first = users.objects.get(username="teacher_one")
    second = users.objects.get(username="teacher_two")
    pdf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(pdf)
    pdf_bytes = pdf.getvalue()
    png = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(png, format="PNG")
    with cabinet_scope(first.pk) as first_alias:
        student = Student.objects.create(name="First cabinet only", grade=7)
        school_class = SchoolClass.objects.create(name="7А", subject="Математика", level="Базовый")
        payment = Payment.objects.create(student=student, amount_rub=600, paid_on="2026-11-05")
        worksheet = Worksheet.objects.create(student=student, title="Private worksheet", kind="homework")
        submission = Submission(worksheet=worksheet, original_name="work.pdf")
        submission.file.save("work.pdf", ContentFile(b"first submission"))
        name = default_storage.save("materials/shared.pdf", ContentFile(pdf_bytes))
        material = Material.objects.create(student=student, title="Private material",
                                           original_name="book.pdf", file=name, page_count=1)
        MaterialPage.objects.create(material=material, number=1)
        exercise = Exercise.objects.create(title="Private exercise", prompt="1+1", subject="Математика")
        ExerciseGrade.objects.create(exercise=exercise, grade=7)
        figure = TaskFigure(exercise=exercise)
        figure.file.save("figure.png", ContentFile(png.getvalue()))
        first_auth = auth_path()
        first_auth.write_text("{}")

    with cabinet_scope(second.pk) as second_alias:
        other_student = Student.objects.create(name="Second cabinet only", grade=8)
        name = default_storage.save("materials/shared.pdf", ContentFile(b"%PDF-1.4 second"))
        assert name == material.file.name
        other_material = Material.objects.create(student=other_student, title="Second material",
                                                 original_name="book.pdf", file=name, page_count=1)
        assert auth_path() != first_auth and not auth_path().exists()

    if settings.TUTOR_POSTGRES_DB:
        for alias in (first_alias, second_alias):
            with connections[alias].cursor() as cursor:
                cursor.execute("SELECT current_database(), current_schema()")
                assert cursor.fetchone() == (settings.TUTOR_POSTGRES_DB, alias)
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('students_student')")
            assert cursor.fetchone() == (None,)
        call_command("migrate_cabinets", verbosity=0)

    def read_file(response):
        assert response.status_code == 200, response.status_code
        try:
            return b"".join(response.streaming_content)
        finally:
            response.close()

    def sign_in(client, username):
        assert client.get("/login/").status_code == 200
        token = client.cookies["csrftoken"].value
        response = client.post("/login/", {"username": username, "password": password,
                                           "csrfmiddlewaretoken": token})
        assert response.status_code == 302 and response.url == "/", response.status_code

    anonymous = Client(HTTP_HOST="localhost")
    assert anonymous.get("/").url == "/login/"
    assert anonymous.get("/profile/").url == "/login/?next=/profile/"
    assert anonymous.get("/api/students").status_code == 401
    assert anonymous.get(f"/api/materials/{material.pk}/file").status_code == 401
    assert anonymous.get("/api/data/backup/export").status_code == 401

    newcomer = Client(HTTP_HOST="localhost", enforce_csrf_checks=True)
    assert b'href="/register/"' in newcomer.get("/login/").content
    assert newcomer.get("/register/").status_code == 200
    registration = {"username": "new_teacher", "password1": password, "password2": password}
    assert newcomer.post("/register/", registration).status_code == 403
    registration["csrfmiddlewaretoken"] = newcomer.cookies["csrftoken"].value
    duplicate = newcomer.post("/register/", {**registration, "username": "TEACHER_ONE"})
    assert duplicate.status_code == 200 and b"errorlist" in duplicate.content
    invalid = newcomer.post("/register/", {**registration, "password2": "does-not-match"})
    assert invalid.status_code == 200 and b"errorlist" in invalid.content
    assert users.objects.count() == 2

    existing_directories = set(cabinet_directory(first.pk).parent.iterdir())
    with patch("config.cabinets.call_command", side_effect=OSError("test migration failure")):
        failed = newcomer.post("/register/", registration)
    assert failed.status_code == 503 and users.objects.count() == 2
    assert set(cabinet_directory(first.pk).parent.iterdir()) == existing_directories
    assert newcomer.get("/api/students").status_code == 401

    created = newcomer.post("/register/", registration)
    assert created.status_code == 302 and created.url == "/"
    assert b"new_teacher" in newcomer.get("/").content
    assert newcomer.get("/api/students").json() == []
    assert newcomer.get(f"/api/students/{student.pk}").status_code == 404
    assert newcomer.get(f"/api/materials/{material.pk}/file").status_code == 404
    assert newcomer.get("/register/").url == "/"

    owner = Client(HTTP_HOST="localhost", enforce_csrf_checks=True)
    visitor = Client(HTTP_HOST="localhost", enforce_csrf_checks=True)
    sign_in(owner, "teacher_one")
    sign_in(visitor, "teacher_two")
    assert b"teacher_one" in owner.get("/").content
    assert b"teacher_two" in visitor.get("/school/").content
    for page in ("/", "/schedule/", "/assignments/", "/finances/", "/data/", "/school/",
                 "/school/schedule/", "/school/assignments/", "/profile/"):
        response = owner.get(page)
        assert response.status_code == 200 and b'class="account-menu"' in response.content, page
    owner_token = owner.cookies["csrftoken"].value
    assert owner.post("/profile/", {"display_name": "No CSRF token"}).status_code == 403
    renamed = owner.post("/profile/", {"display_name": "Анна Смирнова", "username": "teacher_two"},
                         HTTP_X_CSRFTOKEN=owner_token, follow=True)
    assert renamed.status_code == 200 and "Имя сохранено." in renamed.content.decode()
    assert "Анна Смирнова" in owner.get("/").content.decode()
    assert "Анна Смирнова" not in visitor.get("/profile/").content.decode()
    first.refresh_from_db()
    assert first.username == "teacher_one" and first.first_name == "Анна Смирнова"
    first_ids = {item["id"] for item in owner.get("/api/students").json()}
    second_ids = {item["id"] for item in visitor.get("/api/students").json()}
    assert first_ids == {str(student.pk)}
    assert second_ids == {str(other_student.pk)}
    for url in (f"/api/students/{student.pk}", f"/api/assignments/worksheets/{worksheet.pk}",
                f"/api/assignments/worksheets/{worksheet.pk}/pdf",
                f"/api/assignments/submissions/{submission.pk}/file",
                f"/api/materials/{material.pk}/file", f"/api/materials/{material.pk}/page/1.png"):
        assert visitor.get(url).status_code == 404, url
    token = visitor.cookies["csrftoken"].value
    assert visitor.delete(f"/api/finances/payments/{payment.pk}", HTTP_X_CSRFTOKEN=token).status_code == 404
    assert visitor.get("/api/finances/").json()["students"][0]["paid_rub"] == 0
    assert owner.get("/api/finances/").json()["students"][0]["paid_rub"] == 600
    assert read_file(owner.get(f"/api/materials/{material.pk}/file")) == pdf_bytes
    page = owner.get(f"/api/materials/{material.pk}/page/1.png")
    assert page.status_code == 200 and page.content.startswith(b"\x89PNG")
    assert read_file(visitor.get(f"/api/materials/{other_material.pk}/file")) == b"%PDF-1.4 second"
    assert read_file(owner.get(f"/api/assignments/submissions/{submission.pk}/file")) == b"first submission"

    for collection, calendar, owner_field in (
        ("/api/schedule/lessons", "/api/schedule/", {"student_id": str(student.pk)}),
        ("/api/school/schedule/lessons", "/api/school/schedule", {"class_id": str(school_class.pk)}),
    ):
        lesson_fields = {**owner_field, "date": "2026-11-05", "time": "10:00", "duration_min": 45}
        created = owner.post(collection, lesson_fields, content_type="application/json", HTTP_X_CSRFTOKEN=owner_token)
        assert created.status_code == 201, created.content
        detail = f"{collection}/{created.json()['id']}"
        moved_fields = {**lesson_fields, "date": "2026-11-06", "time": "11:00"}
        assert visitor.put(detail, moved_fields, content_type="application/json", HTTP_X_CSRFTOKEN=token).status_code == 404
        moved = owner.put(detail, moved_fields, content_type="application/json", HTTP_X_CSRFTOKEN=owner_token)
        assert moved.status_code == 200, moved.content
        week = f"{calendar}?week=2026-11-02"
        assert [(lesson["date"], lesson["time"]) for lesson in owner.get(week).json()["lessons"]] == [
            ("2026-11-06", "11:00"),
        ]
        assert visitor.get(week).json()["lessons"] == []
        assert owner.delete(detail, data={}, content_type="application/json", HTTP_X_CSRFTOKEN=owner_token).status_code == 200

    backup = read_file(owner.get("/api/data/backup/export"))
    with zipfile.ZipFile(io.BytesIO(backup)) as archive:
        assert b"Second cabinet only" not in archive.read("records.json")
        assert archive.read("uploads/materials/shared.pdf") == pdf_bytes
        assert archive.read(f"uploads/{figure.file.name}") == png.getvalue()
    imported = visitor.post("/api/data/backup/restore", {
        "confirm": "RESTORE", "file": SimpleUploadedFile("archive.zip", backup),
    }, HTTP_X_CSRFTOKEN=token)
    assert imported.status_code == 200, imported.content[:500]
    assert read_file(visitor.get(f"/api/materials/{material.pk}/file")) == pdf_bytes
    assert read_file(owner.get(f"/api/materials/{material.pk}/file")) == pdf_bytes
    assert visitor.get(f"/api/materials/{other_material.pk}/file").status_code == 404
    assert first_auth.exists()

    if export_path:
        Path(export_path).write_bytes(backup)
    if import_path:
        sqlite_archive = Path(import_path).read_bytes()
        migrated = newcomer.post("/api/data/backup/restore", {
            "confirm": "RESTORE", "file": SimpleUploadedFile("sqlite.zip", sqlite_archive),
        }, HTTP_X_CSRFTOKEN=newcomer.cookies["csrftoken"].value)
        assert migrated.status_code == 200, migrated.content[:500]
        exported = read_file(newcomer.get("/api/data/backup/export"))
        with zipfile.ZipFile(io.BytesIO(sqlite_archive)) as before, zipfile.ZipFile(io.BytesIO(exported)) as after:
            expected = json.loads(before.read("manifest.json"))
            actual = json.loads(after.read("manifest.json"))
            assert actual["counts"] == expected["counts"]
            assert actual["files"] == expected["files"]
        with cabinet_scope(users.objects.get(username="new_teacher").pk):
            imported_material = Material.objects.get()
            imported_exercise = Exercise.objects.get()
            MaterialPage.objects.create(material=imported_material, number=2)
            ExerciseGrade.objects.create(exercise=imported_exercise, grade=8)

    assert anonymous.get("/settings/").status_code == 302
    assert anonymous.get("/settings/password/").status_code == 302
    assert owner.post("/settings/", {"start_mode": "school"}).status_code == 403
    assert owner.post("/settings/", {"start_mode": "invalid"}, HTTP_X_CSRFTOKEN=owner_token).status_code == 200
    saved = owner.post("/settings/", {"start_mode": "school"}, HTTP_X_CSRFTOKEN=owner_token)
    assert saved.status_code == 302 and saved.url == "/settings/"
    assert b'value="school" selected' in owner.get("/settings/").content
    assert b'value="tutoring" selected' in visitor.get("/settings/").content

    new_password = "Changed-Local-Test-" + secrets.token_urlsafe(16)
    change = {"old_password": password, "new_password1": new_password, "new_password2": new_password}
    assert owner.get("/settings/password/").status_code == 200
    assert owner.post("/settings/password/", change).status_code == 403
    invalid = owner.post("/settings/password/", {**change, "old_password": "wrong"}, HTTP_X_CSRFTOKEN=owner_token)
    assert invalid.status_code == 200 and b"errorlist" in invalid.content
    first.refresh_from_db()
    assert first.check_password(password)
    changed = owner.post("/settings/password/", change, HTTP_X_CSRFTOKEN=owner_token, follow=True)
    assert changed.status_code == 200 and "Пароль изменён." in changed.content.decode()
    assert owner.get("/profile/").status_code == 200
    assert owner.post("/logout/", {"csrfmiddlewaretoken": owner.cookies["csrftoken"].value}).status_code == 302
    assert owner.get("/login/").status_code == 200
    login = {"username": "teacher_one", "csrfmiddlewaretoken": owner.cookies["csrftoken"].value}
    assert owner.post("/login/", {**login, "password": password}).status_code == 200
    signed_in = owner.post("/login/", {**login, "password": new_password, "next": "https://example.com/"})
    assert signed_in.status_code == 302 and signed_in.url == "/school/"
    assert owner.post("/logout/", {"csrfmiddlewaretoken": owner.cookies["csrftoken"].value}).status_code == 302
    destination = owner.post("/login/", {**login, "password": new_password, "next": "/assignments/",
                                         "csrfmiddlewaretoken": owner.cookies["csrftoken"].value})
    assert destination.status_code == 302 and destination.url == "/assignments/"
    assert visitor.post("/logout/", {"csrfmiddlewaretoken": token}).status_code == 302
    assert visitor.get("/api/students").status_code == 401
    sign_in(visitor, "teacher_two")


if __name__ == "__main__":
    from argparse import ArgumentParser

    parser = ArgumentParser()
    parser.add_argument("--export", dest="export_path")
    parser.add_argument("--import", dest="import_path")
    check_cabinet_isolation(**vars(parser.parse_args()))
