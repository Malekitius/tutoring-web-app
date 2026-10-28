import io
import json
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from config.portability import create_archive, inspect_archive, restore_archive
from students.models import Student

from .models import SchoolClass, SchoolLesson, SchoolStudent, SchoolWeeklyRule


class SchoolFlowTests(TestCase):
    def send(self, method, path, data):
        return getattr(self.client, method)(path, data=json.dumps(data), content_type="application/json")

    def school_class(self, name="8А"):
        return SchoolClass.objects.create(name=name, subject="Алгебра", level="Углублённый")

    def lesson_data(self, school_class, **changes):
        return {"class_id": str(school_class.id), "date": "2026-10-26", "time": "10:00",
                "duration_min": 45, "topic": "Уравнения", **changes}

    def test_mode_pages_are_available(self):
        self.assertContains(self.client.get("/school/"), "Создать класс")
        self.assertContains(self.client.get("/school/schedule/"), "Расписание классов")
        self.assertContains(self.client.get("/"), "Репетиторство")

    def test_class_and_students_are_independent_of_tutoring_records(self):
        tutor = Student.objects.create(name="Индивидуальный ученик", grade=8)
        created = self.send("post", "/api/school/classes", {
            "name": "8А", "subject": "Алгебра", "level": "Углублённый",
        })
        self.assertEqual(created.status_code, 201)
        class_id = created.json()["id"]
        self.assertEqual(self.send("post", "/api/school/classes", {
            "name": "8А", "subject": "Алгебра", "level": "Базовый",
        }).status_code, 409)
        students = []
        for group in ("support", "mastering", "advanced"):
            response = self.send("post", f"/api/school/classes/{class_id}/students", {
                "name": f"Ученик {group}", "group": group,
                "birth_date": "2012-05-12", "comment": "Наблюдение",
            })
            self.assertEqual(response.status_code, 201)
            students.append(response.json())
        self.assertEqual({item["group"] for item in self.client.get(f"/api/school/classes/{class_id}").json()["students"]},
                         {"support", "mastering", "advanced"})
        edited = self.send("put", f"/api/school/students/{students[0]['id']}", {
            "name": "Ирина", "group": "advanced", "birth_date": "2012-05-12", "comment": "Готова к олимпиаде",
        })
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.json()["comment"], "Готова к олимпиаде")
        self.assertEqual(self.send("post", f"/api/school/classes/{class_id}/students", {
            "name": "Ошибка", "group": "other", "birth_date": "", "comment": "",
        }).status_code, 400)
        self.assertEqual(self.send("delete", f"/api/school/students/{students[1]['id']}", {}).status_code, 200)
        self.assertEqual(SchoolStudent.objects.count(), 2)
        self.assertEqual(Student.objects.get(id=tutor.id).name, "Индивидуальный ученик")

    def test_weekly_school_lessons_can_be_overridden_and_series_ended(self):
        school_class = self.school_class()
        created = self.send("post", "/api/school/schedule/lessons", self.lesson_data(school_class, repeat_weekly=True))
        self.assertEqual(created.status_code, 201, created.content)
        rule_id = created.json()["weekly_rule_id"]
        next_week = self.client.get("/api/school/schedule?week=2026-11-02").json()
        self.assertEqual(len(next_week["lessons"]), 1)
        occurrence = next_week["lessons"][0]
        changed = self.send("put", f"/api/school/schedule/lessons/{occurrence['id']}",
                            self.lesson_data(school_class, date="2026-11-03", time="11:00", topic="Неравенства"))
        self.assertEqual(changed.status_code, 200, changed.content)
        self.assertEqual(changed.json()["source_date"], "2026-11-02")
        self.assertEqual(self.client.get("/api/school/schedule?week=2026-11-02").json()["lessons"][0]["date"], "2026-11-03")
        following = self.client.get("/api/school/schedule?week=2026-11-09").json()["lessons"]
        self.assertEqual([(item["date"], item["time"]) for item in following], [("2026-11-09", "10:00")])
        self.assertEqual(self.send("patch", f"/api/school/schedule/lessons/{occurrence['id']}", {"status": "completed"}).status_code, 200)
        self.assertEqual(self.send("delete", f"/api/school/schedule/rules/{rule_id}", {"from_date": "2026-11-09"}).status_code, 200)
        self.assertFalse(self.client.get("/api/school/schedule?week=2026-11-16").json()["lessons"])
        self.assertEqual(SchoolLesson.objects.get(id=occurrence["id"]).status, "completed")

    def test_school_and_tutor_calendars_reject_overlaps_in_both_directions(self):
        school_class = self.school_class()
        tutor = Student.objects.create(name="Индивидуальный ученик", grade=8)
        tutor_lesson = self.send("post", "/api/schedule/lessons", {
            "student_id": str(tutor.id), "date": "2026-10-26", "time": "10:00", "duration_min": 60,
        })
        self.assertEqual(tutor_lesson.status_code, 201)
        self.assertEqual(self.send("post", "/api/school/schedule/lessons", self.lesson_data(school_class, time="10:30")).status_code, 400)
        self.send("delete", f"/api/schedule/lessons/{tutor_lesson.json()['id']}", {})
        school_lesson = self.send("post", "/api/school/schedule/lessons", self.lesson_data(school_class))
        self.assertEqual(school_lesson.status_code, 201)
        self.assertEqual(self.send("post", "/api/schedule/lessons", {
            "student_id": str(tutor.id), "date": "2026-10-26", "time": "10:30", "duration_min": 60,
        }).status_code, 400)

    def test_series_change_keeps_manually_moved_lesson_free_of_overlap(self):
        school_class = self.school_class()
        rule_id = self.send("post", "/api/school/schedule/lessons",
                            self.lesson_data(school_class, repeat_weekly=True)).json()["weekly_rule_id"]
        occurrence = self.client.get("/api/school/schedule?week=2026-11-02").json()["lessons"][0]
        self.assertEqual(self.send("put", f"/api/school/schedule/lessons/{occurrence['id']}",
                                   self.lesson_data(school_class, date="2026-11-02", time="11:00")).status_code, 200)
        changed = self.send("put", f"/api/school/schedule/rules/{rule_id}", {
            "from_date": "2026-10-26", "class_id": str(school_class.id),
            "weekday": 0, "time": "11:00", "duration_min": 45, "topic": "Новая тема",
        })
        self.assertEqual(changed.status_code, 400)

    def test_backup_restores_school_data_and_reads_old_archive(self):
        with tempfile.TemporaryDirectory() as folder, override_settings(DATA_DIR=Path(folder), MEDIA_ROOT=Path(folder) / "uploads"):
            school_class = self.school_class()
            student = SchoolStudent.objects.create(school_class=school_class, name="Мария", group="advanced", birth_date=date(2012, 4, 3))
            rule = SchoolWeeklyRule.objects.create(school_class=school_class, weekday=0, time="10:00", start_date="2026-10-26")
            SchoolLesson.objects.create(school_class=school_class, date="2026-10-26", time="10:00", weekly_rule=rule, source_date="2026-10-26")
            archive = create_archive()
            data = archive.read()
            archive.close()
            student.name = "Изменено"
            student.save()
            restore_archive(SimpleUploadedFile("school-backup.zip", data))
            self.assertEqual(SchoolStudent.objects.get(id=student.id).name, "Мария")
            self.assertEqual(SchoolLesson.objects.count(), 1)

            SchoolLesson.objects.all().delete()
            SchoolWeeklyRule.objects.all().delete()
            SchoolStudent.objects.all().delete()
            SchoolClass.objects.all().delete()
            empty = create_archive()
            with zipfile.ZipFile(empty) as source:
                records = source.read("records.json")
                manifest = json.loads(source.read("manifest.json"))
            empty.close()
            manifest["version"] = 1
            manifest["counts"] = {key: value for key, value in manifest["counts"].items() if not key.startswith("school.")}
            old = io.BytesIO()
            with zipfile.ZipFile(old, "w") as target:
                target.writestr("records.json", records)
                target.writestr("manifest.json", json.dumps(manifest))
            legacy = SimpleUploadedFile("legacy.zip", old.getvalue())
            self.assertEqual(inspect_archive(legacy)[1]["school.schoolclass"], 0)
            SchoolClass.objects.create(name="Временный", subject="Физика", level="Базовый")
            restore_archive(SimpleUploadedFile("legacy.zip", old.getvalue()))
            self.assertFalse(SchoolClass.objects.exists())
