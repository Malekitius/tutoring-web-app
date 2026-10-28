"""Round-trip checks for the complete, versioned application archive."""

import io
import hashlib
import json
import tempfile
import uuid
import zipfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from assignments.models import Exercise, ExerciseGrade, Submission, Worksheet, WorksheetItem
from finances.models import Payment
from schedule.models import Lesson, LessonComment, WeeklyRule

from .models import Student, Subject, Topic


class BackupTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_root = Path(self.temp.name)
        self.media_root = self.data_root / "uploads"
        self.media_root.mkdir()
        settings_override = override_settings(DATA_DIR=self.data_root, MEDIA_ROOT=self.media_root)
        settings_override.enable()
        self.addCleanup(settings_override.disable)

    def upload(self, content):
        return SimpleUploadedFile("tutor-backup.zip", content, content_type="application/zip")

    def test_archive_restores_students_schedule_tasks_finances_and_uploads(self):
        student = Student.objects.create(name="Ученик", grade=8, price_rub=1300, opening_balance_rub=200)
        subject = Subject.objects.create(student=student, name="Алгебра", icon="algebra")
        Topic.objects.create(subject=subject, title="Уравнения", mastery=2)
        rule = WeeklyRule.objects.create(student=student, subject=subject, weekday=1, time="16:00", start_date="2026-10-20")
        lesson = Lesson.objects.create(student=student, subject=subject, date="2026-10-20", time="16:00",
                                       status="completed", charged_price_rub=1200, weekly_rule=rule,
                                       source_date="2026-10-20", is_override=True)
        LessonComment.objects.create(student=student, lesson=lesson, body="Повторить тему")
        Payment.objects.create(student=student, paid_on="2026-10-20", amount_rub=2000)
        exercise = Exercise.objects.create(title="Пример", prompt="$x+1=2$", subject="Алгебра")
        ExerciseGrade.objects.create(exercise=exercise, grade=8)
        worksheet = Worksheet.objects.create(student=student, lesson=lesson, kind="homework", title="Уравнения")
        WorksheetItem.objects.create(worksheet=worksheet, source=exercise, title="Пример", prompt="$x+1=2$")
        file_name = f"assignments/{worksheet.id}/work.pdf"
        file_path = self.media_root / file_name
        file_path.parent.mkdir(parents=True)
        file_path.write_bytes(b"%PDF-1.4 test")
        Submission.objects.create(worksheet=worksheet, file=file_name, original_name="work.pdf")

        response = self.client.get("/api/data/backup/export")
        self.assertEqual(response.status_code, 200)
        archive_bytes = b"".join(response.streaming_content)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            self.assertIn(f"uploads/{file_name}", archive.namelist())
            self.assertNotIn("assistant_auth.json", archive.namelist())

        student.name = "Изменено"
        student.save()
        Payment.objects.all().delete()
        file_path.write_bytes(b"changed")
        preview = self.client.post("/api/data/backup/preview", {"file": self.upload(archive_bytes)})
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(preview.json()["archive"]["finances.payment"], 1)
        restored = self.client.post("/api/data/backup/restore", {
            "file": self.upload(archive_bytes), "confirm": "RESTORE",
        })
        self.assertEqual(restored.status_code, 200, restored.content)
        self.assertEqual(Student.objects.get(id=student.id).name, "Ученик")
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(Lesson.objects.get(id=lesson.id).charged_price_rub, 1200)
        self.assertEqual(Worksheet.objects.get(id=worksheet.id).items.count(), 1)
        self.assertEqual(file_path.read_bytes(), b"%PDF-1.4 test")
        self.assertTrue((self.data_root / "backups" / restored.json()["recovery_file"]).exists())

    def test_archive_rejects_missing_media_before_changing_data(self):
        student = Student.objects.create(name="Ученик", grade=5)
        worksheet = Worksheet.objects.create(student=student, kind="homework", title="Работа")
        Submission.objects.create(worksheet=worksheet, file="assignments/missing.pdf", original_name="missing.pdf")
        response = self.client.get("/api/data/backup/export")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Student.objects.count(), 1)

    def test_failed_restore_rolls_back_records_and_uploads(self):
        student = Student.objects.create(name="Прежние данные", grade=7)
        Payment.objects.create(student=student, paid_on="2026-10-20", amount_rub=800)
        worksheet = Worksheet.objects.create(student=student, kind="homework", title="Работа")
        file_name = f"assignments/{worksheet.id}/work.pdf"
        file_path = self.media_root / file_name
        file_path.parent.mkdir(parents=True)
        file_path.write_bytes(b"original upload")
        Submission.objects.create(worksheet=worksheet, file=file_name, original_name="work.pdf")
        original = b"".join(self.client.get("/api/data/backup/export").streaming_content)
        with zipfile.ZipFile(io.BytesIO(original)) as source:
            records = json.loads(source.read("records.json"))
            for row in records:
                if row["model"] == "finances.payment":
                    row["fields"]["student"] = str(uuid.uuid4())
            records_bytes = json.dumps(records, ensure_ascii=False).encode("utf-8")
            manifest = json.loads(source.read("manifest.json"))
            manifest["files"]["records.json"] = {
                "sha256": hashlib.sha256(records_bytes).hexdigest(), "size": len(records_bytes),
            }
            tampered = io.BytesIO()
            with zipfile.ZipFile(tampered, "w") as target:
                target.writestr("records.json", records_bytes)
                target.writestr("uploads/" + file_name, b"original upload")
                target.writestr("manifest.json", json.dumps(manifest))
        response = self.client.post("/api/data/backup/restore", {
            "file": self.upload(tampered.getvalue()), "confirm": "RESTORE",
        })
        self.assertEqual(response.status_code, 400, response.content)
        self.assertTrue(Student.objects.filter(id=student.id, name="Прежние данные").exists())
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(file_path.read_bytes(), b"original upload")
