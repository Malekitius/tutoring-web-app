import json
from datetime import date

from django.test import TestCase

from students.models import Student, Subject

from .models import Lesson, LessonComment, WeeklyRule


class ScheduleTests(TestCase):
    def setUp(self):
        self.student = Student.objects.create(name="Тестовый ученик", grade=5, duration_min=60)
        self.subject = Subject.objects.create(student=self.student, name="Математика")

    def send(self, method, path, data):
        return getattr(self.client, method)(path, data=json.dumps(data), content_type="application/json")

    def fields(self, **changes):
        result = {
            "student_id": str(self.student.id), "subject_id": str(self.subject.id),
            "date": "2026-10-19", "time": "16:00", "duration_min": 60,
        }
        result.update(changes)
        return result

    def test_weekly_occurrence_and_single_lesson_override(self):
        response = self.send("post", "/api/schedule/lessons", self.fields(repeat_weekly=True))
        self.assertEqual(response.status_code, 201)
        week = self.client.get("/api/schedule/?week=2026-10-26").json()
        self.assertEqual(len(week["lessons"]), 1)
        item = week["lessons"][0]
        self.assertEqual(item["date"], "2026-10-26")
        response = self.send("put", f"/api/schedule/lessons/{item['id']}", self.fields(
            date="2026-10-27", time="17:00", status="completed",
        ))
        self.assertEqual(response.status_code, 200)
        week = self.client.get("/api/schedule/?week=2026-10-26").json()
        self.assertEqual([(x["date"], x["status"]) for x in week["lessons"]], [("2026-10-27", "completed")])
        next_week = self.client.get("/api/schedule/?week=2026-11-02").json()
        self.assertEqual(next_week["lessons"][0]["date"], "2026-11-02")
        self.assertEqual(next_week["lessons"][0]["time"], "16:00")

    def test_collision_is_rejected(self):
        first = self.send("post", "/api/schedule/lessons", self.fields())
        self.assertEqual(first.status_code, 201)
        second = self.send("post", "/api/schedule/lessons", self.fields(time="16:30"))
        self.assertEqual(second.status_code, 400)
        self.assertEqual(Lesson.objects.count(), 1)
        week = self.send("post", "/api/schedule/lessons", self.fields(repeat_weekly=True))
        self.assertEqual(week.status_code, 400)
        self.assertEqual(WeeklyRule.objects.count(), 0)

    def test_series_change_preserves_history_and_changes_future(self):
        response = self.send("post", "/api/schedule/lessons", self.fields(repeat_weekly=True))
        rule_id = response.json()["weekly_rule_id"]
        first_id = response.json()["id"]
        done = self.send("put", f"/api/schedule/lessons/{first_id}", self.fields(status="completed"))
        self.assertEqual(done.status_code, 200)
        changed = self.send("put", f"/api/schedule/rules/{rule_id}", {
            "from_date": "2026-10-26", "student_id": str(self.student.id),
            "subject_id": str(self.subject.id), "weekday": 1,
            "time": "18:00", "duration_min": 90,
        })
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(Lesson.objects.get(id=first_id).status, "completed")
        week = self.client.get("/api/schedule/?week=2026-10-26").json()
        self.assertEqual([(item["date"], item["time"]) for item in week["lessons"]], [("2026-10-27", "18:00")])
        self.assertEqual(WeeklyRule.objects.filter(start_date=date(2026, 10, 27)).count(), 1)

    def test_cancellation_of_one_occurrence_keeps_series(self):
        self.send("post", "/api/schedule/lessons", self.fields(repeat_weekly=True))
        week = self.client.get("/api/schedule/?week=2026-10-26").json()
        item = week["lessons"][0]
        response = self.send("put", f"/api/schedule/lessons/{item['id']}", self.fields(
            date="2026-10-26", status="cancelled",
        ))
        self.assertEqual(response.status_code, 200)
        again = self.client.get("/api/schedule/?week=2026-10-26").json()
        self.assertEqual(again["lessons"][0]["status"], "cancelled")
        following = self.client.get("/api/schedule/?week=2026-11-02").json()
        self.assertEqual(following["lessons"][0]["status"], "planned")

    def test_ending_entire_series_frees_its_slot(self):
        created = self.send("post", "/api/schedule/lessons", self.fields(
            date="2026-10-28", repeat_weekly=True,
        ))
        self.assertEqual(created.status_code, 201)
        rule_id = created.json()["weekly_rule_id"]
        ended = self.send("delete", f"/api/schedule/rules/{rule_id}", {"from_date": "2026-10-28"})
        self.assertEqual(ended.status_code, 200)
        recreated = self.send("post", "/api/schedule/lessons", self.fields(
            date="2026-10-21", repeat_weekly=True,
        ))
        self.assertEqual(recreated.status_code, 201, recreated.content)

    def test_multiple_comments_can_be_edited_and_deleted(self):
        lesson_id = self.send("post", "/api/schedule/lessons", self.fields()).json()["id"]
        path = f"/api/schedule/lessons/{lesson_id}/comments"
        first = self.send("post", path, {
            "body": "Подготовить дроби", "priority": "high", "due_date": "2026-10-22",
        })
        self.assertEqual(first.status_code, 201)
        second = self.send("post", path, {"body": "Повторить таблицу умножения"})
        self.assertEqual(second.status_code, 201)
        comments = self.client.get("/api/schedule/?week=2026-10-19").json()["lessons"][0]["comments"]
        self.assertEqual(len(comments), 2)
        self.assertEqual(comments[0]["priority"], "high")
        self.assertEqual(comments[0]["due_date"], "2026-10-22")
        self.assertEqual(comments[1]["priority"], "none")
        self.assertIsNone(comments[1]["due_date"])
        edited = self.send("put", f"/api/schedule/comments/{first.json()['id']}", {
            "body": "Новые задачи на дроби", "priority": "medium", "due_date": None,
        })
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.json()["priority"], "medium")
        self.assertIsNone(edited.json()["due_date"])
        deleted = self.send("delete", f"/api/schedule/comments/{second.json()['id']}", {})
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(list(LessonComment.objects.values_list("body", flat=True)), ["Новые задачи на дроби"])

    def test_comment_validation(self):
        lesson_id = self.send("post", "/api/schedule/lessons", self.fields()).json()["id"]
        path = f"/api/schedule/lessons/{lesson_id}/comments"
        for payload in (
            {"body": " "},
            {"body": "Задача", "priority": "urgent"},
            {"body": "Задача", "priority": []},
            {"body": "Задача", "due_date": "не дата"},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.send("post", path, payload).status_code, 400)
        self.assertEqual(LessonComment.objects.count(), 0)

    def test_lesson_comments_use_priority_and_deadline_order(self):
        lesson_id = self.send("post", "/api/schedule/lessons", self.fields()).json()["id"]
        path = f"/api/schedule/lessons/{lesson_id}/comments"
        for comment in (
            {"body": "Без приоритета"},
            {"body": "Высокий позже", "priority": "high", "due_date": "2026-10-30"},
            {"body": "Высокий раньше", "priority": "high", "due_date": "2026-10-23"},
        ):
            self.assertEqual(self.send("post", path, comment).status_code, 201)
        week = self.client.get("/api/schedule/?week=2026-10-19").json()
        self.assertEqual([item["body"] for item in week["lessons"][0]["comments"]], [
            "Высокий раньше", "Высокий позже", "Без приоритета",
        ])

    def test_comment_survives_change_of_weekly_series(self):
        created = self.send("post", "/api/schedule/lessons", self.fields(repeat_weekly=True)).json()
        week = self.client.get("/api/schedule/?week=2026-10-26").json()
        occurrence_id = week["lessons"][0]["id"]
        self.assertEqual(self.send("post", f"/api/schedule/lessons/{occurrence_id}/comments", {
            "body": "Проверить ДЗ", "priority": "low",
        }).status_code, 201)
        self.assertTrue(Lesson.objects.get(id=occurrence_id).is_override)
        changed = self.send("put", f"/api/schedule/rules/{created['weekly_rule_id']}", {
            "from_date": "2026-10-26", "student_id": str(self.student.id),
            "subject_id": str(self.subject.id), "weekday": 1,
            "time": "18:00", "duration_min": 90,
        })
        self.assertEqual(changed.status_code, 200)
        self.assertTrue(LessonComment.objects.filter(lesson_id=occurrence_id, body="Проверить ДЗ").exists())
        self.assertEqual(len(self.client.get("/api/schedule/?week=2026-10-26").json()["lessons"][0]["comments"]), 1)
