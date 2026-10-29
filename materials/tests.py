import io
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from pypdf import PdfWriter

from assignments.pdf_export import build_source
from assistant.providers import user_content
from assistant.views import requested_source_numbers
from config.portability import create_archive, restore_archive
from school.models import SchoolClass, SchoolWorksheet
from students.models import Student

from .context import selected_context
from .models import Material, MaterialPage


def blank_pdf():
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    writer.write(output)
    return output.getvalue()


class MaterialTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings_context = override_settings(DATA_DIR=Path(self.temp.name), MEDIA_ROOT=Path(self.temp.name) / "uploads")
        self.settings_context.enable()
        self.addCleanup(self.settings_context.disable)
        self.student = Student.objects.create(name="Тестовый ученик", grade=8)
        self.school_class = SchoolClass.objects.create(name="8А", subject="Алгебра", level="Базовый")

    def upload(self, owner_key, owner_id):
        return self.client.post("/api/materials/", {
            owner_key: str(owner_id), "title": "Учебник алгебры", "kind": "textbook",
            "file": SimpleUploadedFile("algebra.pdf", blank_pdf(), content_type="application/pdf"),
        })

    def test_explicit_source_number_lists_and_ranges(self):
        self.assertEqual(requested_source_numbers("№ 69, 70, 71 и 72"), ["69", "70", "71", "72"])
        self.assertEqual(requested_source_numbers("69-72"), ["69", "70", "71", "72"])
        self.assertEqual(requested_source_numbers("после № 69"), [])

    def test_upload_for_student_and_class_then_delete(self):
        first = self.upload("student_id", self.student.id)
        second = self.upload("class_id", self.school_class.id)
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(second.status_code, 201, second.content)
        self.assertEqual(first.json()["page_count"], 1)
        self.assertEqual(first.json()["text_page_count"], 0)
        self.assertEqual(len(self.client.get(f"/api/materials/?student_id={self.student.id}").json()), 1)
        self.assertEqual(len(self.client.get(f"/api/materials/?class_id={self.school_class.id}").json()), 1)
        file_response = self.client.get(first.json()["url"])
        self.assertEqual(file_response.status_code, 200)
        self.assertEqual(file_response["X-Frame-Options"], "SAMEORIGIN")
        self.assertIn("inline", file_response["Content-Disposition"])
        self.assertTrue(b"".join(file_response.streaming_content).startswith(b"%PDF-"))
        file_response.close()
        page_response = self.client.get(f"/api/materials/{first.json()['id']}/page/1.png")
        self.assertEqual(page_response.status_code, 200)
        self.assertTrue(page_response.content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(self.client.get(f"/api/materials/{first.json()['id']}/page/2.png").status_code, 404)
        path = Material.objects.get(id=first.json()["id"]).file.path
        self.assertEqual(self.client.delete(f"/api/materials/{first.json()['id']}").status_code, 200)
        self.assertFalse(Path(path).exists())

    def test_crop_figure_from_pdf_page(self):
        material = self.upload("student_id", self.student.id).json()
        cropped = self.client.post(f"/api/materials/{material['id']}/crop",
                                   json.dumps({"page": 1, "x": .1, "y": .1, "width": .5, "height": .3}),
                                   content_type="application/json")
        self.assertEqual(cropped.status_code, 200, cropped.content)
        import base64
        self.assertTrue(base64.b64decode(cropped.json()["png"]).startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(cropped.json()["source_page"], 1)
        invalid = self.client.post(f"/api/materials/{material['id']}/crop",
                                   json.dumps({"page": 1, "x": .9, "y": .9, "width": .3, "height": .3}),
                                   content_type="application/json")
        self.assertEqual(invalid.status_code, 400)

    def test_school_task_keeps_cropped_figure(self):
        material = self.upload("class_id", self.school_class.id).json()
        figure = self.client.post(f"/api/materials/{material['id']}/crop",
                                  json.dumps({"page": 1, "x": .1, "y": .1, "width": .5, "height": .3}),
                                  content_type="application/json").json()
        exercise = {"title": "График", "prompt": "Исследуйте график", "answer": "Ответ",
                    "subject": "Алгебра", "topic": "Функции", "subtopic": "", "difficulty": 2,
                    "grades": [8], "figures": [figure]}
        saved = self.client.post("/api/assistant/accept", json.dumps({"class_id": str(self.school_class.id),
            "grade": 8, "destination": "lesson", "title": "Графики", "exercises": [exercise]}),
            content_type="application/json")
        self.assertEqual(saved.status_code, 201, saved.content)
        worksheet = SchoolWorksheet.objects.get(id=saved.json()["worksheet"]["id"])
        self.assertEqual(worksheet.items.first().figures.count(), 1)
        self.assertEqual(self.client.get(f"/api/school/worksheets/{worksheet.id}/pdf").status_code, 200)

    def test_invalid_and_foreign_materials_are_rejected(self):
        fake = self.client.post("/api/materials/", {
            "student_id": str(self.student.id), "title": "Не PDF", "kind": "other",
            "file": SimpleUploadedFile("fake.pdf", b"not a PDF", content_type="application/pdf"),
        })
        self.assertEqual(fake.status_code, 400)
        created = self.upload("student_id", self.student.id).json()
        with self.assertRaisesRegex(ValueError, "не относится"):
            selected_context([{"id": created["id"], "pages": "1"}],
                             {"school_class": self.school_class}, "алгебра")

    def test_local_text_search_and_explicit_scan_pages(self):
        material = Material(student=self.student, title="Алгебра", kind="textbook", original_name="algebra.pdf", page_count=1)
        material.file.save("algebra.pdf", ContentFile(blank_pdf()), save=False)
        material.save()
        MaterialPage.objects.create(material=material, number=1, text="Линейные уравнения. Решите уравнение.")
        text, files, refs = selected_context([{"id": str(material.id), "pages": ""}], {"student": self.student}, "линейные уравнения")
        self.assertIn("Линейные уравнения", text)
        self.assertEqual(files, [])
        self.assertEqual(refs[0]["pages"], [1])
        text, files, refs = selected_context([{"id": str(material.id), "pages": "1"}], {"student": self.student}, "геометрия")
        self.assertEqual(text, "")
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0][1].startswith(b"%PDF-"))
        self.assertEqual(refs[0]["pages"], [1])

    @patch("assistant.views.get_provider")
    def test_generator_reads_selected_student_material(self, factory):
        material = Material(student=self.student, title="Задачник", kind="workbook", original_name="book.pdf", page_count=1)
        material.file.save("book.pdf", ContentFile(blank_pdf()), save=False)
        material.save()
        MaterialPage.objects.create(material=material, number=1, text="Дроби. Сложите одну вторую и одну третью.")
        factory.return_value.complete.return_value = json.dumps({"exercises": [{
            "title": "Сложение дробей", "prompt": "Вычислите $\\frac{1}{2}+\\frac{1}{3}$.",
            "answer": "$\\frac{5}{6}$", "source_material": "Задачник", "source_number": "12",
        }]})
        response = self.client.post("/api/assistant/generate", data=json.dumps({
            "student_id": str(self.student.id), "subject": "Математика", "topic": "Дроби",
            "mode": "source", "count": 1, "materials": [{"id": str(material.id), "pages": "1"}],
        }), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["source_refs"][0]["pages"], [1])
        self.assertIn("Задачник", factory.return_value.complete.call_args.args[1])
        self.assertIn("Сохрани условие", factory.return_value.complete.call_args.args[0])
        self.assertEqual(len(factory.return_value.complete.call_args.kwargs["files"]), 1)

    @patch("assistant.views.get_provider")
    def test_textbook_subparts_are_one_number_in_generated_draft(self, factory):
        material = Material(student=self.student, title="Задачник", kind="workbook", original_name="book.pdf", page_count=1)
        material.file.save("book.pdf", ContentFile(blank_pdf()), save=False)
        material.save()
        MaterialPage.objects.create(material=material, number=1,
                                    text="№ 12. Вычислите: а) 1+1; б) 2+2; в) 3+3; г) 4+4.\n№ 13. Вычислите 5+5.")
        factory.return_value.complete.return_value = json.dumps({"exercises": [{
            "title": "№ 12", "source_material": "Задачник", "source_number": "12", "difficulty": 1,
            "prompt": "№ 12. Вычислите: а) $1+1$; б) $2+2$; в) $3+3$; г) $4+4$.",
            "answer": "а) $2$; б) $4$; в) $6$; г) $8$.",
        }]}, ensure_ascii=False)
        response = self.client.post("/api/assistant/generate", data=json.dumps({
            "student_id": str(self.student.id), "subject": "Математика", "topic": "Сложение",
            "mode": "source", "count": 1, "source_task_hint": "№ 12",
            "materials": [{"id": str(material.id), "pages": "1"}],
        }), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()["exercises"]), 1)
        self.assertEqual(response.json()["exercises"][0]["source_number"], "12")
        for letter in "абвг":
            self.assertIn(f"{letter})", response.json()["exercises"][0]["prompt"])
            self.assertIn(f"{letter})", response.json()["exercises"][0]["answer"])
        instructions, prompt = factory.return_value.complete.call_args.args
        self.assertIn("ОДИН объект", instructions)
        self.assertIn("ВСЕ его подпункты", instructions)
        self.assertIn("порядковый_номер_целого_упражнения_в_подборке", prompt)

    @patch("assistant.views.get_provider")
    def test_source_generation_rejects_repeated_parent_number(self, factory):
        material = Material(student=self.student, title="Задачник", kind="workbook", original_name="book.pdf", page_count=1)
        material.file.save("book.pdf", ContentFile(blank_pdf()), save=False)
        material.save()
        MaterialPage.objects.create(material=material, number=1, text="№ 12. а) 1+1; б) 2+2. № 13. 3+3.")
        factory.return_value.complete.return_value = json.dumps({"exercises": [{
            "title": "№ 12, б)", "source_material": "Задачник", "source_number": "12",
            "prompt": "б) $2+2$.", "answer": "$4$.",
        }]}, ensure_ascii=False)
        response = self.client.post("/api/assistant/generate", data=json.dumps({
            "student_id": str(self.student.id), "subject": "Математика", "topic": "Сложение",
            "mode": "source", "count": 1, "source_index": 2,
            "existing_tasks": ["№ 12. а) $1+1$; б) $2+2$."],
            "existing_source_numbers": [{"source_material": "Задачник", "source_number": "12"}],
            "materials": [{"id": str(material.id), "pages": "1"}],
        }), content_type="application/json")
        self.assertEqual(response.status_code, 502)
        self.assertIn("повторён уже выбранный номер", response.json()["error"])
        self.assertEqual(factory.return_value.complete.call_count, 2)

    @patch("assistant.views.get_provider")
    def test_explicit_second_number_retries_empty_response_with_pdf(self, factory):
        material = Material(student=self.student, title="Задачник", kind="workbook", original_name="book.pdf", page_count=1)
        material.file.save("book.pdf", ContentFile(blank_pdf()), save=False)
        material.save()
        MaterialPage.objects.create(material=material, number=1,
                                    text="Условия и формулы в начале.\n69\n70\n71\n72")
        factory.return_value.complete.side_effect = [
            json.dumps({"exercises": []}),
            json.dumps({"exercises": [{"title": "№ 70", "source_material": "Задачник", "source_number": "70",
                                      "prompt": "а) $u^7v^{12}$; б) $\\frac{u^3}{v^8}$.",
                                      "answer": "а) Ответ; б) ответ."}]}, ensure_ascii=False),
        ]
        response = self.client.post("/api/assistant/generate", data=json.dumps({
            "student_id": str(self.student.id), "subject": "Математика", "topic": "Корни",
            "mode": "source", "count": 1, "source_index": 2, "source_task_hint": "69,70,71,72",
            "existing_tasks": ["Условие № 69"],
            "existing_source_numbers": [{"source_material": "Задачник", "source_number": "69"}],
            "materials": [{"id": str(material.id), "pages": "1"}],
        }), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["exercises"][0]["source_number"], "70")
        self.assertEqual(factory.return_value.complete.call_count, 2)
        first_prompt = json.loads(factory.return_value.complete.call_args_list[0].args[1])
        self.assertEqual(first_prompt["целевой_номер_в_этом_запросе"], "70")
        self.assertEqual(len(factory.return_value.complete.call_args.kwargs["files"]), 1)

    @patch("assistant.views.get_provider")
    def test_scanned_pages_are_sent_as_pdf_snippet(self, factory):
        material = Material(student=self.student, title="Скан задачника", kind="workbook",
                            original_name="scan.pdf", page_count=1)
        material.file.save("scan.pdf", ContentFile(blank_pdf()), save=False)
        material.save()
        factory.return_value.complete.return_value = json.dumps({"exercises": [{
            "title": "Пример", "prompt": "Вычислите $2+2$.", "answer": "$4$",
            "source_material": "Скан задачника", "source_number": "12",
        }]})
        response = self.client.post("/api/assistant/generate", data=json.dumps({
            "student_id": str(self.student.id), "subject": "Математика", "topic": "Сложение",
            "difficulty": 1, "count": 1, "materials": [{"id": str(material.id), "pages": "1"}],
        }), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        sent_files = factory.return_value.complete.call_args.kwargs["files"]
        self.assertEqual(len(sent_files), 1)
        self.assertTrue(sent_files[0][1].startswith(b"%PDF-"))
        self.assertEqual(user_content("Перенеси задачу", sent_files)[1]["type"], "input_file")

    @patch("assistant.views.get_provider")
    def test_generation_modes_do_not_mix_sources(self, factory):
        material = Material(student=self.student, title="Задачник", kind="workbook",
                            original_name="book.pdf", page_count=1)
        material.file.save("book.pdf", ContentFile(blank_pdf()), save=False)
        material.save()
        base = {"student_id": str(self.student.id), "subject": "Математика", "topic": "Сложение",
                "difficulty": 1, "count": 1}
        rejected = self.client.post("/api/assistant/generate", data=json.dumps({
            **base, "mode": "generated", "materials": [{"id": str(material.id), "pages": "1"}],
        }), content_type="application/json")
        self.assertEqual(rejected.status_code, 400)
        missing_pages = self.client.post("/api/assistant/generate", data=json.dumps({
            **base, "mode": "source", "materials": [{"id": str(material.id), "pages": ""}],
        }), content_type="application/json")
        self.assertEqual(missing_pages.status_code, 400)
        factory.return_value.complete.return_value = json.dumps({"exercises": [{
            "title": "Пример", "prompt": "Вычислите $2+2$.", "answer": "$4$",
        }]})
        generated = self.client.post("/api/assistant/generate", data=json.dumps({
            **base, "mode": "generated", "materials": [],
        }), content_type="application/json")
        self.assertEqual(generated.status_code, 200, generated.content)
        self.assertNotIn("files", factory.return_value.complete.call_args.kwargs)
        self.assertEqual(generated.json()["source_refs"], [])

    @patch("assistant.views.get_provider")
    def test_school_generation_and_saved_pdf_workflow(self, factory):
        material = Material(school_class=self.school_class, title="Задачник 8А", kind="workbook",
                            original_name="book.pdf", page_count=1)
        material.file.save("book.pdf", ContentFile(blank_pdf()), save=False)
        material.save()
        MaterialPage.objects.create(material=material, number=1, text="Линейные уравнения. Решите уравнение.")
        factory.return_value.complete.return_value = json.dumps({"exercises": [{
            "title": "Уравнение", "prompt": "Решите $x+2=5$.", "answer": "$x=3$",
            "source_material": "Задачник 8А", "source_number": "12",
        }]})
        generated = self.client.post("/api/assistant/generate", data=json.dumps({
            "class_id": str(self.school_class.id), "subject": "Алгебра", "topic": "Уравнения",
            "difficulty": 1, "count": 1,
            "mode": "source", "materials": [{"id": str(material.id), "pages": "1"}],
        }), content_type="application/json")
        self.assertEqual(generated.status_code, 200, generated.content)
        self.assertEqual(generated.json()["exercises"][0]["grades"], [8])
        exercise = {**generated.json()["exercises"][0], "source_refs": generated.json()["source_refs"]}
        accepted = self.client.post("/api/assistant/accept", data=json.dumps({
            "class_id": str(self.school_class.id), "destination": "homework", "title": "Домашняя работа",
            "exercises": [exercise],
        }), content_type="application/json")
        self.assertEqual(accepted.status_code, 201, accepted.content)
        worksheet = SchoolWorksheet.objects.get(id=accepted.json()["worksheet"]["id"])
        self.assertEqual(worksheet.items.count(), 1)
        self.assertEqual(worksheet.items.first().source_ref, "Задачник 8А, стр. 1")
        source = build_source(worksheet)
        self.assertIn("8А", source)
        self.assertIn("Решите", source)
        teacher_source = build_source(worksheet, include_answers=True)
        self.assertIn("Задачник 8А, стр. 1", teacher_source)
        self.assertNotIn("Задачник 8А, стр. 1", source)
        self.assertEqual(len(self.client.get(f"/api/school/worksheets?class_id={self.school_class.id}").json()), 1)

    @patch("assistant.views.get_provider")
    def test_assistant_can_read_school_class_context(self, factory):
        factory.return_value.complete.return_value = "Класс изучает алгебру."
        response = self.client.post("/api/assistant/ask", data=json.dumps({"question": "Что известно о 8А?"}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("8А", factory.return_value.complete.call_args.args[1])

    def test_archive_restores_pdf_and_school_worksheet(self):
        uploaded = self.upload("class_id", self.school_class.id)
        self.assertEqual(uploaded.status_code, 201)
        worksheet = SchoolWorksheet.objects.create(school_class=self.school_class, kind="lesson", title="Контрольная")
        worksheet_id = worksheet.id
        archive = create_archive()
        data = archive.read()
        archive.close()
        Material.objects.all().delete()
        worksheet.delete()
        restore_archive(SimpleUploadedFile("backup.zip", data))
        restored = Material.objects.get(id=uploaded.json()["id"])
        self.assertTrue(restored.file.path.endswith(".pdf"))
        self.assertTrue(Path(restored.file.path).exists())
        self.assertTrue(SchoolWorksheet.objects.filter(id=worksheet_id).exists())

    def test_previous_v2_archive_restores_without_new_tables(self):
        archive = create_archive()
        with zipfile.ZipFile(archive) as source:
            records = source.read("records.json")
            manifest = json.loads(source.read("manifest.json"))
        archive.close()
        manifest["version"] = 2
        manifest["counts"] = {key: value for key, value in manifest["counts"].items()
                              if not key.startswith("materials.") and key not in
                              {"school.schoolworksheet", "school.schoolworksheetitem", "assignments.taskfigure"}}
        old = io.BytesIO()
        with zipfile.ZipFile(old, "w") as target:
            target.writestr("records.json", records)
            target.writestr("manifest.json", json.dumps(manifest))
        self.upload("student_id", self.student.id)
        restore_archive(SimpleUploadedFile("legacy-v2.zip", old.getvalue()))
        self.assertFalse(Material.objects.exists())
