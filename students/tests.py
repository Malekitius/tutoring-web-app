import json

from django.test import Client, TestCase
from schedule.models import Lesson, LessonComment

from .icons import SUBJECT_ICONS, default_icon_for_name
from .models import Student, Subject, Topic


class StudentCardTest(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.get("/")
        self.csrf = {"HTTP_X_CSRFTOKEN": self.client.cookies["csrftoken"].value}

    def write(self, method, path, payload=None):
        return getattr(self.client, method)(
            path,
            data=json.dumps(payload) if payload is not None else None,
            content_type="application/json",
            **self.csrf,
        )

    def test_card_subjects_topics_and_cascade(self):
        created = self.write("post", "/api/students", {
            "name": "Тестовый ученик", "grade": 6, "status": "active",
            "goal": "Уверенно решать задачи",
            "price_rub": 2000, "duration_min": 60,
        })
        self.assertEqual(created.status_code, 201)
        student_id = created.json()["id"]

        subject = self.write("post", f"/api/students/{student_id}/subjects", {
            "name": "Математика", "level": "базовый", "goal": "Освоить уравнения",
        })
        self.assertEqual(subject.status_code, 201)
        subject_id = subject.json()["id"]

        topic = self.write("post", f"/api/subjects/{subject_id}/topics", {
            "title": "Дроби", "mastery": 1, "notes": "Ошибки при сложении",
        })
        self.assertEqual(topic.status_code, 201)
        topic_id = topic.json()["id"]

        changed = self.write("put", f"/api/topics/{topic_id}", {
            "title": "Дроби", "mastery": 2, "notes": "Закрепляем",
        })
        self.assertEqual(changed.status_code, 200)
        card = self.client.get(f"/api/students/{student_id}").json()
        self.assertEqual(card["subjects"][0]["topics"][0]["mastery"], 2)
        self.assertEqual(self.client.get("/api/students").json()[0]["subject_count"], 1)

        self.assertEqual(self.write("delete", f"/api/students/{student_id}").status_code, 200)
        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(Subject.objects.count(), 0)
        self.assertEqual(Topic.objects.count(), 0)

    def test_invalid_grade_and_duplicate_subject(self):
        bad = self.write("post", "/api/students", {"name": "Тест", "grade": 12})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(Student.objects.count(), 0)

        created = self.write("post", "/api/students", {"name": "Тест", "grade": 4})
        student_id = created.json()["id"]
        path = f"/api/students/{student_id}/subjects"
        payload = {"name": "Математика", "level": "базовый"}
        self.assertEqual(self.write("post", path, payload).status_code, 201)
        self.assertEqual(self.write("post", path, payload).status_code, 409)

    def test_custom_subject_can_be_added_renamed_and_used_in_schedule(self):
        student_id = self.write("post", "/api/students", {"name": "Тест", "grade": 8}).json()["id"]
        path = f"/api/students/{student_id}/subjects"
        created = self.write("post", path, {"name": "  Алгебра  ", "level": "базовый"})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["name"], "Алгебра")
        subject_id = created.json()["id"]
        renamed = self.write("put", f"/api/subjects/{subject_id}", {
            "name": "Геометрия", "level": "уверенный",
        })
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["name"], "Геометрия")
        card = self.client.get(f"/api/students/{student_id}").json()
        self.assertEqual(card["subjects"][0]["name"], "Геометрия")
        week = self.client.get("/api/schedule/?week=2026-10-22").json()
        self.assertEqual(week["students"][0]["subjects"][0]["name"], "Геометрия")
        self.assertEqual(self.write("post", path, {"name": " ", "level": "базовый"}).status_code, 400)
        self.assertEqual(self.write("post", path, {"name": "А" * 81, "level": "базовый"}).status_code, 400)

    def test_subject_icon_can_be_selected_and_changed(self):
        student_id = self.write("post", "/api/students", {"name": "Тест", "grade": 8}).json()["id"]
        path = f"/api/students/{student_id}/subjects"
        created = self.write("post", path, {"name": "Физика", "icon": "physics"})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["icon"], "physics")
        subject_id = created.json()["id"]
        changed = self.write("put", f"/api/subjects/{subject_id}", {
            "name": "Физика", "icon": "astronomy",
        })
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()["icon"], "astronomy")
        self.assertEqual(self.client.get(f"/api/students/{student_id}").json()["subjects"][0]["icon"], "astronomy")
        invalid = self.write("put", f"/api/subjects/{subject_id}", {"name": "Физика", "icon": "<script>"})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.write("put", f"/api/subjects/{subject_id}", {"name": "Физика", "icon": []}).status_code, 400)
        self.assertEqual(Subject.objects.get(id=subject_id).icon, "astronomy")

        default = self.write("post", path, {"name": "Алгебра"})
        self.assertEqual(default.status_code, 201)
        self.assertEqual(default.json()["icon"], "algebra")
        self.assertEqual(default_icon_for_name(" Физика "), "physics")
        self.assertEqual(next(icon["symbol"] for icon in SUBJECT_ICONS if icon["id"] == "physics"), "φ")
        self.assertContains(self.client.get("/"), 'id="subject-icons-data"')

    def test_write_requires_csrf(self):
        unauthenticated = Client(enforce_csrf_checks=True)
        response = unauthenticated.post(
            "/api/students", data=json.dumps({"name": "Тест", "grade": 4}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_student_notes_are_shared_with_lessons_and_sorted(self):
        created = self.write("post", "/api/students", {"name": "Тестовый ученик 1", "grade": 5})
        student_id = created.json()["id"]
        lesson = Lesson.objects.create(student_id=student_id, date="2026-10-22", time="16:00")
        linked = self.write("post", f"/api/schedule/lessons/{lesson.id}/comments", {
            "body": "Разобрать дроби", "priority": "high", "due_date": "2026-10-25",
        })
        self.assertEqual(linked.status_code, 201)
        self.assertEqual(linked.json()["student_id"], student_id)
        for body, priority, due_date in (
            ("Без приоритета", "none", None),
            ("Низкий", "low", "2026-10-23"),
            ("Средний", "medium", "2026-10-24"),
            ("Высокий без даты", "high", None),
            ("Срочный дедлайн", "high", "2026-10-23"),
        ):
            result = self.write("post", f"/api/students/{student_id}/notes", {
                "body": body, "priority": priority, "due_date": due_date,
            })
            self.assertEqual(result.status_code, 201)
        notes = self.client.get(f"/api/students/{student_id}").json()["notes"]
        self.assertEqual([note["body"] for note in notes], [
            "Срочный дедлайн", "Разобрать дроби", "Высокий без даты",
            "Средний", "Низкий", "Без приоритета",
        ])
        self.assertEqual(notes[1]["lesson_id"], str(lesson.id))
        self.assertEqual(notes[1]["lesson_date"], "2026-10-22")

        changed = self.write("put", f"/api/notes/{linked.json()['id']}", {
            "body": "Повторить дроби", "priority": "medium", "due_date": None,
        })
        self.assertEqual(changed.status_code, 200)
        week = self.client.get("/api/schedule/?week=2026-10-22").json()
        self.assertEqual(week["lessons"][0]["comments"][0]["body"], "Повторить дроби")
        self.assertEqual(self.write("delete", f"/api/notes/{linked.json()['id']}").status_code, 200)
        self.assertEqual(self.client.get("/api/schedule/?week=2026-10-22").json()["lessons"][0]["comments"], [])

    def test_lesson_note_follows_student_change_and_survives_lesson_deletion(self):
        first = self.write("post", "/api/students", {"name": "Тестовый ученик 1", "grade": 5}).json()
        second = self.write("post", "/api/students", {"name": "Тестовый ученик 2", "grade": 6}).json()
        lesson = Lesson.objects.create(student_id=first["id"], date="2026-10-22", time="16:00")
        note_id = self.write("post", f"/api/schedule/lessons/{lesson.id}/comments", {
            "body": "Проверить решение", "priority": "low",
        }).json()["id"]
        moved = self.write("put", f"/api/schedule/lessons/{lesson.id}", {
            "student_id": second["id"], "subject_id": "", "date": "2026-10-22",
            "time": "16:00", "duration_min": 60, "status": "planned",
        })
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(self.client.get(f"/api/students/{first['id']}").json()["notes"], [])
        self.assertEqual(self.client.get(f"/api/students/{second['id']}").json()["notes"][0]["id"], note_id)
        self.assertEqual(self.write("delete", f"/api/schedule/lessons/{lesson.id}").status_code, 200)
        retained = self.client.get(f"/api/students/{second['id']}").json()["notes"][0]
        self.assertEqual(retained["id"], note_id)
        self.assertIsNone(retained["lesson_id"])
