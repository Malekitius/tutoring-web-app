"""Workspace restores must preserve the other mode and the shared library."""

import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path

from django.core import serializers
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from assignments.models import Exercise, ExerciseGrade, Worksheet, WorksheetItem, TaskFigure, Submission
from finances.models import Payment
from materials.models import Material, MaterialPage
from school.models import SchoolClass, SchoolStudent, SchoolLesson, SchoolWorksheet, SchoolWorksheetItem
from students.models import Student, Subject
from schedule.models import Lesson, LessonComment
from .portability import FILE_MODELS, create_archive, inspect_archive, scope_querysets


class ScopedArchiveTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.enterContext(override_settings(DATA_DIR=root, MEDIA_ROOT=root / "uploads"))
        self.library = Exercise.objects.create(title="Общая задача", prompt="Общее условие", subject="Алгебра")
        ExerciseGrade.objects.create(exercise=self.library, grade=8)
        self.library_figure = self.figure(exercise=self.library)
        self.student = Student.objects.create(name="Репетиторство", grade=8, price_rub=1500)
        subject = Subject.objects.create(student=self.student, name="Алгебра")
        lesson = Lesson.objects.create(student=self.student, subject=subject, date="2026-10-29", time="16:00", status="completed", charged_price_rub=1500)
        LessonComment.objects.create(student=self.student, lesson=lesson, body="Заметка")
        self.payment = Payment.objects.create(student=self.student, paid_on="2026-10-29", amount_rub=3000)
        sheet = Worksheet.objects.create(student=self.student, lesson=lesson, title="Индивидуальная работа", kind="homework")
        self.tutor_item = WorksheetItem.objects.create(worksheet=sheet, source=self.library, title="Копия", prompt="Условие для ученика")
        self.figure(worksheet_item=self.tutor_item)
        submission = Submission(worksheet=sheet, original_name="work.pdf")
        submission.file.save("work.pdf", ContentFile(b"student work"))
        self.school = SchoolClass.objects.create(name="8А", subject="Алгебра")
        self.school_student = SchoolStudent.objects.create(school_class=self.school, name="Школьный ученик")
        SchoolLesson.objects.create(school_class=self.school, date="2026-10-29", time="09:00")
        school_sheet = SchoolWorksheet.objects.create(school_class=self.school, title="Работа класса", kind="lesson")
        self.school_item = SchoolWorksheetItem.objects.create(worksheet=school_sheet, source=self.library, title="Копия", prompt="Условие для класса")
        self.school_figure = self.figure(school_item=self.school_item)
        self.tutor_material = self.material(student=self.student)
        self.school_material = self.material(school_class=self.school)

    def figure(self, **owner):
        figure = TaskFigure(**owner, source_title="Учебник", source_page=1)
        figure.file.save("figure.png", ContentFile(b"independent figure snapshot"))
        return figure

    def material(self, **owner):
        material = Material(**owner, title="Материал", original_name="book.pdf", page_count=1)
        material.file.save("book.pdf", ContentFile(b"%PDF-1.4 material"))
        MaterialPage.objects.create(material=material, number=1, text="Текст страницы")
        return material

    def export(self, scope):
        response = self.client.get("/api/data/backup/export", {"scope": scope})
        self.assertEqual(response.status_code, 200)
        data = b"".join(response.streaming_content)
        response.close()
        return data

    def restore(self, data, scope):
        return self.client.post("/api/data/backup/restore", {
            "file": SimpleUploadedFile("backup.zip", data), "scope": scope, "confirm": "RESTORE",
        })

    def snapshot(self, scope):
        querysets = scope_querysets(scope)
        records = [serializers.serialize("json", rows.order_by("pk")) for rows in querysets.values()]
        files = {}
        for model in FILE_MODELS:
            for item in querysets[model]:
                with item.file.open("rb") as stream:
                    files[item.file.name] = stream.read()
        return records, files

    def library_snapshot(self):
        return (serializers.serialize("json", Exercise.objects.order_by("pk")),
                serializers.serialize("json", ExerciseGrade.objects.order_by("pk")),
                serializers.serialize("json", TaskFigure.objects.filter(exercise__isnull=False).order_by("pk")),
                Path(self.library_figure.file.path).read_bytes())

    def rewrite(self, data, edit):
        with zipfile.ZipFile(io.BytesIO(data)) as source:
            records = json.loads(source.read("records.json"))
            manifest = json.loads(source.read("manifest.json"))
            edit(records, manifest)
            content = json.dumps(records, ensure_ascii=False).encode()
            manifest["files"]["records.json"] = {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w") as target:
                for name in source.namelist():
                    if name not in {"records.json", "manifest.json"}:
                        target.writestr(name, source.read(name))
                target.writestr("records.json", content)
                target.writestr("manifest.json", json.dumps(manifest))
        return output.getvalue()

    def assert_isolated_restore(self, scope):
        data = self.export(scope)
        self.student.name = "Новое имя репетиторства"
        self.student.save()
        self.school.name = "Новое имя школы"
        self.school.save()
        self.library.prompt = "Библиотеку изменили после копирования"
        self.library.save()
        Path(self.library_figure.file.path).write_bytes(b"new shared figure")
        other_scope = "school" if scope == "tutoring" else "tutoring"
        other_before, library_before = self.snapshot(other_scope), self.library_snapshot()
        material = self.tutor_material if scope == "tutoring" else self.school_material
        Path(material.file.path).write_bytes(b"changed local file")
        response = self.restore(data, scope)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.snapshot(other_scope), other_before)
        self.assertEqual(self.library_snapshot(), library_before)
        self.assertEqual(Path(material.file.path).read_bytes(), b"%PDF-1.4 material")
        item = WorksheetItem.objects.get(pk=self.tutor_item.pk) if scope == "tutoring" else SchoolWorksheetItem.objects.get(pk=self.school_item.pk)
        self.assertEqual(item.source_id, self.library.pk)
        self.assertTrue((Path(self.temp.name) / "backups" / response.json()["recovery_file"]).exists())

    def test_tutoring_restore_preserves_school_and_library(self):
        self.assert_isolated_restore("tutoring")
        self.assertEqual(Student.objects.get(pk=self.student.pk).name, "Репетиторство")
        self.assertEqual(Payment.objects.get(pk=self.payment.pk).amount_rub, 3000)

    def test_school_restore_preserves_tutoring_and_library(self):
        self.assert_isolated_restore("school")
        self.assertEqual(SchoolClass.objects.get(pk=self.school.pk).name, "8А")

    def test_scoped_export_has_no_other_mode_or_library_records(self):
        data = self.export("school")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            records = json.loads(archive.read("records.json"))
            self.assertEqual(manifest["scope"], "school")
            self.assertFalse(any(row["model"].startswith(("students.", "finances.", "schedule.")) for row in records))
            self.assertFalse(any(row["model"] == "assignments.exercise" for row in records))
            self.assertNotIn("uploads/" + self.tutor_material.file.name, archive.namelist())
            self.assertNotIn("uploads/" + self.library_figure.file.name, archive.namelist())

    def test_restore_without_library_keeps_task_snapshot(self):
        data = self.export("school")
        self.library.delete()
        before = self.snapshot("tutoring")
        response = self.restore(data, "school")
        self.assertEqual(response.status_code, 200, response.content)
        item = SchoolWorksheetItem.objects.get(pk=self.school_item.pk)
        self.assertIsNone(item.source_id)
        self.assertEqual(item.prompt, "Условие для класса")
        self.assertEqual(item.figures.count(), 1)
        self.assertEqual(self.snapshot("tutoring"), before)
        self.assertFalse(Exercise.objects.exists())

    def test_material_page_ids_can_overlap_across_devices(self):
        data = self.export("school")
        material_id = self.school_material.pk
        old_page_id = self.school_material.pages.get().pk
        self.school_material.delete()
        collision = MaterialPage.objects.create(pk=old_page_id, material=self.tutor_material, number=2, text="Не менять")
        response = self.restore(data, "school")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(MaterialPage.objects.get(pk=collision.pk).text, "Не менять")
        self.assertEqual(MaterialPage.objects.filter(material_id=material_id).count(), 1)

    def test_scope_mismatch_and_library_figure_collision_are_rejected(self):
        data = self.export("school")
        before = self.snapshot("all")
        self.assertEqual(self.restore(data, "tutoring").status_code, 400)
        self.assertEqual(self.snapshot("all"), before)
        figure_id = self.school_figure.pk
        self.school_figure.delete()
        collision = TaskFigure(id=figure_id, exercise=self.library, source_page=1)
        collision.file.save("collision.png", ContentFile(b"keep library file"))
        before = self.snapshot("all")
        self.assertEqual(self.restore(data, "school").status_code, 400)
        self.assertEqual(self.snapshot("all"), before)

    def test_empty_school_archive_clears_only_school(self):
        content = b"[]"
        manifest = {"format": "tutoring-web-app.backup", "version": 5, "scope": "school",
                    "created_at": "2026-10-29T12:00:00+00:00",
                    "counts": {model._meta.label_lower: 0 for model in scope_querysets()},
                    "files": {"records.json": {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}}}
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("records.json", content)
            archive.writestr("manifest.json", json.dumps(manifest))
        tutor, library = self.snapshot("tutoring"), self.library_snapshot()
        response = self.restore(output.getvalue(), "school")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(SchoolClass.objects.exists())
        self.assertFalse(Path(self.school_material.file.path).exists())
        self.assertEqual(self.snapshot("tutoring"), tutor)
        self.assertEqual(self.library_snapshot(), library)

    def test_failed_partial_restore_rolls_back_records_and_files(self):
        data = self.export("school")
        def invalidate(records, manifest):
            next(row for row in records if row["model"] == "school.schoolstudent")["fields"]["name"] = None
        tampered = self.rewrite(data, invalidate)
        before = self.snapshot("all")
        response = self.restore(tampered, "school")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self.snapshot("all"), before)

    def test_old_full_archive_is_readable_and_not_mistaken_for_a_mode(self):
        data = self.export("all")
        def legacy(records, manifest):
            manifest["version"] = 4
            manifest.pop("scope")
        old = self.rewrite(data, legacy)
        self.assertEqual(inspect_archive(SimpleUploadedFile("old.zip", old))[1]["students.student"], 1)
        self.assertEqual(self.restore(old, "school").status_code, 400)
