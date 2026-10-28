import json
import shutil
import uuid
from datetime import date
from tempfile import TemporaryDirectory
from unittest import skipUnless

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from schedule.models import Lesson
from students.models import Student

from .models import Exercise, Submission, Worksheet, WorksheetItem


class AssignmentFlowTests(TestCase):
    def setUp(self):
        self.student = Student.objects.create(name="Тестовый ученик", grade=5)
        self.other = Student.objects.create(name="Другой тестовый ученик", grade=6)
        self.lesson = Lesson.objects.create(student=self.student, date=date(2026, 10, 26), time="16:00")

    def post_json(self, path, payload):
        return self.client.post(path, json.dumps(payload), content_type="application/json")

    def test_library_task_is_copied_into_lesson_and_homework(self):
        exercise = self.post_json("/api/assignments/exercises", {
            "title": "Дроби", "prompt": "1/2 + 1/3", "answer": "5/6",
            "subject": "Математика", "grade": 5, "topic": "Дроби",
        }).json()
        ids = []
        for kind in ("lesson", "homework"):
            response = self.post_json("/api/assignments/worksheets", {
                "student_id": str(self.student.id), "lesson_id": str(self.lesson.id),
                "kind": kind, "title": "Тренировка дробей", "instructions": "Решить подробно",
                "due_date": "2026-10-29" if kind == "homework" else None,
            })
            self.assertEqual(response.status_code, 201)
            sheet_id = response.json()["id"]
            ids.append(sheet_id)
            item = self.post_json(f"/api/assignments/worksheets/{sheet_id}/items", {"source_id": exercise["id"]})
            self.assertEqual(item.status_code, 201)
            self.assertEqual(item.json()["prompt"], "1/2 + 1/3")

        changed = {**exercise, "prompt": "Другой пример"}
        response = self.client.put(f"/api/assignments/exercises/{exercise['id']}", json.dumps(changed), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        for sheet_id in ids:
            detail = self.client.get(f"/api/assignments/worksheets/{sheet_id}").json()
            self.assertEqual(detail["items"][0]["prompt"], "1/2 + 1/3")

    def test_lesson_must_belong_to_student(self):
        response = self.post_json("/api/assignments/worksheets", {
            "student_id": str(self.other.id), "lesson_id": str(self.lesson.id),
            "kind": "homework", "title": "Проверка",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Worksheet.objects.count(), 0)

    def test_library_filters_and_facets(self):
        first = self.post_json("/api/assignments/exercises", {
            "title": "Сложение дробей", "prompt": "Вычислите $1+2$", "answer": "3",
            "subject": "Математика", "grades": [5, 6], "topic": "Дроби",
            "subtopic": "Сложение", "difficulty": 2,
        })
        self.assertEqual(first.status_code, 201)
        self.post_json("/api/assignments/exercises", {
            "title": "Сила", "prompt": "Найдите силу", "answer": "",
            "subject": "Физика", "grades": [8], "topic": "Механика",
            "subtopic": "Законы Ньютона", "difficulty": 4,
        })
        self.post_json("/api/assignments/exercises", {
            "title": "Алгоритмы", "prompt": "Опишите алгоритм", "answer": "",
            "subject": "Информатика", "grades": [8], "topic": "Алгоритмы",
            "subtopic": "", "difficulty": 3,
        })
        response = self.client.get("/api/assignments/exercises", {
            "subject": "Математика", "topic": "Дроби", "subtopic": "Сложение",
            "grade": "6", "difficulty": "2", "q": "Вычислите",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["items"][0]["grades"], [5, 6])
        self.assertEqual(response.json()["facets"]["topics"], ["Дроби"])
        self.assertEqual(self.client.get("/api/assignments/exercises", {"grade": 8}).json()["total"], 2)
        self.assertEqual(self.client.get("/api/assignments/exercises", {"page_size": 1}).json()["total"], 3)
        self.assertIn("Информатика", self.client.get("/api/assignments/exercises").json()["facets"]["subjects"])
        multiple = self.client.get("/api/assignments/exercises", {
            "subject": ["Математика", "Физика"], "topic": ["Дроби", "Механика"],
            "subtopic": ["Сложение", "Законы Ньютона"], "grade": ["5", "8"],
            "difficulty": ["2", "4"],
        })
        self.assertEqual(multiple.status_code, 200)
        self.assertEqual(multiple.json()["total"], 2)
        self.assertEqual(set(multiple.json()["facets"]["topics"]), {"Дроби", "Механика"})
        self.assertEqual(self.client.get("/api/assignments/exercises", {"grade": ["5", "6"]}).json()["total"], 1)
        self.assertEqual(self.client.get("/api/assignments/exercises", {"difficulty": ["2", "5"]}).status_code, 400)

    def test_library_export_import_roundtrip_and_copy_stability(self):
        exercise = self.post_json("/api/assignments/exercises", {
            "title": "Уравнение", "prompt": r"Решите $x+2=4$.", "answer": "$x=2$",
            "subject": "Математика", "grades": [5, 6], "topic": "Уравнения",
            "subtopic": "Линейные", "difficulty": 2,
        }).json()
        sheet = Worksheet.objects.create(student=self.student, kind="lesson", title="Урок")
        self.post_json(f"/api/assignments/worksheets/{sheet.id}/items", {"source_id": exercise["id"]})
        response = self.client.get("/api/assignments/library/export")
        self.assertEqual(response.status_code, 200)
        exported = json.loads(response.content)
        self.assertEqual(exported["format"], "tutoring-web-app.exercise-library")
        self.assertEqual(exported["version"], 2)
        self.assertEqual(exported["exercises"][0]["grades"], [5, 6])
        self.assertEqual(set(exported["exercises"][0]), {"id", "title", "prompt", "answer", "subject", "grades", "topic", "subtopic", "difficulty"})
        self.assertNotIn("Тестовый ученик", response.content.decode())
        exported["exercises"][0]["prompt"] = "Другое условие"
        exported["exercises"].append({**exported["exercises"][0], "id": str(uuid.uuid4()), "title": "Новая"})
        def upload():
            return SimpleUploadedFile("library.json", json.dumps(exported, ensure_ascii=False).encode(), content_type="application/json")
        preview = self.client.post("/api/assignments/library/import?dry_run=1", {"file": upload()}).json()
        self.assertEqual((preview["created"], preview["updated"]), (1, 1))
        self.assertEqual(Exercise.objects.count(), 1)
        imported = self.client.post("/api/assignments/library/import", {"file": upload()}).json()
        self.assertEqual((imported["created"], imported["updated"]), (1, 1))
        self.assertEqual(Exercise.objects.count(), 2)
        self.assertEqual(self.client.post("/api/assignments/library/import", {"file": upload()}).json()["unchanged"], 2)
        self.assertEqual(sheet.items.first().prompt, r"Решите $x+2=4$.")

    def test_library_import_rejects_invalid_file_atomically(self):
        valid = {"id": str(uuid.uuid4()), "title": "Новая", "prompt": "Текст", "answer": "",
                 "subject": "Математика", "grades": [5], "topic": "", "subtopic": "", "difficulty": 3}
        invalid = {**valid, "id": str(uuid.uuid4()), "difficulty": 9}
        document = {"format": "tutoring-web-app.exercise-library", "version": 1, "exercises": [valid, invalid]}
        upload = SimpleUploadedFile("library.json", json.dumps(document).encode(), content_type="application/json")
        self.assertEqual(self.client.post("/api/assignments/library/import", {"file": upload}).status_code, 400)
        self.assertEqual(Exercise.objects.count(), 0)

    def test_legacy_library_maps_difficulty_without_assigning_olympiad(self):
        rows = [{"id": str(uuid.uuid4()), "title": f"Задача {level}", "prompt": "Условие",
                 "answer": "", "subject": "Математика", "grades": [5], "topic": "", "subtopic": "",
                 "difficulty": level} for level in range(1, 6)]
        document = {"format": "tutoring-web-app.exercise-library", "version": 1, "exercises": rows}
        upload = SimpleUploadedFile("old.json", json.dumps(document).encode(), content_type="application/json")
        response = self.client.post("/api/assignments/library/import", {"file": upload})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([Exercise.objects.get(id=row["id"]).difficulty for row in rows], [1, 2, 2, 3, 3])

    def test_batch_add_preserves_selection_order_and_rejects_duplicates_atomically(self):
        sheet = Worksheet.objects.create(student=self.student, kind="homework", title="Подборка")
        sources = [Exercise.objects.create(title=f"Задача {index}", prompt=f"Условие {index}",
                                           subject="Математика", difficulty=level)
                   for index, level in enumerate((1, 3, 4))]
        url = f"/api/assignments/worksheets/{sheet.id}/items/batch"
        selected = [str(sources[2].id), str(sources[0].id)]
        response = self.post_json(url, {"exercise_ids": selected})
        self.assertEqual(response.status_code, 201)
        self.assertEqual([item["source_id"] for item in response.json()["items"]], selected)
        self.assertEqual([item.source_id for item in sheet.items.all()], [sources[2].id, sources[0].id])
        invalid = self.post_json(url, {"exercise_ids": [str(sources[1].id), str(uuid.uuid4())]})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(sheet.items.count(), 2)
        duplicate = self.post_json(url, {"exercise_ids": [str(sources[1].id), str(sources[1].id)]})
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(sheet.items.count(), 2)
        existing = self.post_json(url, {"exercise_ids": [str(sources[1].id), selected[0]]})
        self.assertEqual(existing.status_code, 400)
        self.assertEqual(sheet.items.count(), 2)

    def test_difficulty_four_is_olympiad_and_five_is_rejected(self):
        payload = {"title": "Олимпиада", "prompt": "Условие", "answer": "",
                   "subject": "Математика", "grades": [8], "difficulty": 4}
        self.assertEqual(self.post_json("/api/assignments/exercises", payload).status_code, 201)
        self.assertEqual(self.post_json("/api/assignments/exercises", {**payload, "difficulty": 5}).status_code, 400)
        self.assertEqual(self.client.get("/api/assignments/exercises", {"difficulty": 4}).json()["total"], 1)

    def test_submission_review_and_file_cleanup(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            sheet = Worksheet.objects.create(student=self.student, kind="homework", title="Проверка")
            upload = SimpleUploadedFile("решение.pdf", b"%PDF-1.4\n%test", content_type="application/pdf")
            response = self.client.post(f"/api/assignments/worksheets/{sheet.id}/submissions", {"file": upload, "note": "Версия 1"})
            self.assertEqual(response.status_code, 201)
            submission = Submission.objects.get(worksheet=sheet)
            file_response = self.client.get(f"/api/assignments/submissions/{submission.id}/file")
            self.assertEqual(file_response.status_code, 200)
            file_response.close()
            sheet.refresh_from_db()
            self.assertEqual(sheet.status, "submitted")
            response = self.client.patch(f"/api/assignments/worksheets/{sheet.id}",
                                         json.dumps({"status": "reviewed", "feedback": "Проверить знаменатель"}),
                                         content_type="application/json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["feedback"], "Проверить знаменатель")
            path = submission.file.path
            self.assertTrue(submission.file.storage.exists(submission.file.name))
            self.client.delete(f"/api/assignments/submissions/{submission.id}")
            self.assertFalse(submission.file.storage.exists(submission.file.name))

    def test_upload_rejects_invalid_file(self):
        sheet = Worksheet.objects.create(student=self.student, kind="homework", title="Проверка")
        upload = SimpleUploadedFile("fake.pdf", b"not a pdf", content_type="application/pdf")
        response = self.client.post(f"/api/assignments/worksheets/{sheet.id}/submissions", {"file": upload})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Submission.objects.count(), 0)

    @skipUnless(shutil.which("xelatex"), "XeLaTeX не установлен")
    def test_pdf_export_with_math_and_separate_answers(self):
        sheet = Worksheet.objects.create(student=self.student, kind="homework", title="Дроби")
        WorksheetItem.objects.create(worksheet=sheet, position=1, title="Сложение",
                                     prompt=r"Вычислите $\frac{1}{2}+\frac{1}{3}$.", answer=r"Ответ: $\boxed{\frac{5}{6}}\,.$")
        student_pdf = self.client.get(f"/api/assignments/worksheets/{sheet.id}/pdf")
        answer_pdf = self.client.get(f"/api/assignments/worksheets/{sheet.id}/pdf?solutions=1")
        self.assertEqual(student_pdf.status_code, 200)
        self.assertEqual(answer_pdf.status_code, 200)
        self.assertTrue(student_pdf.content.startswith(b"%PDF-"))
        self.assertTrue(answer_pdf.content.startswith(b"%PDF-"))
        self.assertNotEqual(student_pdf.content, answer_pdf.content)
