import base64
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image, PngImagePlugin

from assignments.models import Exercise
from finances.models import Payment
from school.models import SchoolClass
from students.models import Student
from .providers import ChatGPTPlanProvider, OpenAIResponsesProvider, user_content
from .screenshots import prepare_screenshots


class ScreenshotGenerationTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=Path(self.temp.name) / "uploads"))
        self.student = Student.objects.create(name="Тестовый ученик", grade=7, opening_balance_rub=500)
        self.payment = Payment.objects.create(student=self.student, paid_on="2026-10-30", amount_rub=1500)
        self.payload = {"student_id": str(self.student.id), "subject": "Алгебра", "topic": "Уравнения",
                        "mode": "generated", "difficulty": 1, "count": 1,
                        "wishes": "Не бери № 3; для № 5 создай похожую задачу с другими числами"}
        self.task = {"exercises": [{"title": "Уравнение", "prompt": "Решите $2x=6$.", "answer": "$x=3$."}]}

    def screenshot(self, index=0, size=(120, 80)):
        image = Image.new("RGB", size, (index * 30, 60, 120))
        output = io.BytesIO()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("private_metadata", "Не передавать")
        image.save(output, format="PNG", pnginfo=metadata)
        return SimpleUploadedFile(f"screen-{index}.png", output.getvalue(), content_type="image/png")

    def generate(self, screenshots, payload=None):
        return self.client.post("/api/assistant/generate", {"payload": json.dumps(payload or self.payload),
                                                           "screenshots": screenshots})

    @patch("assistant.views.get_provider")
    def test_six_screenshots_and_comment_reach_provider_in_order_without_saving(self, factory):
        factory.return_value.complete.return_value = json.dumps(self.task)
        response = self.generate([self.screenshot(index) for index in range(6)])
        self.assertEqual(response.status_code, 200, response.content)
        instructions, prompt = factory.return_value.complete.call_args.args
        images = factory.return_value.complete.call_args.kwargs["images"]
        self.assertEqual(len(images), 6)
        for index, (mime, content) in enumerate(images):
            self.assertEqual(mime, "image/png")
            with Image.open(io.BytesIO(content)) as image:
                self.assertEqual(image.getpixel((0, 0)), (index * 30, 60, 120))
                self.assertNotIn("private_metadata", image.info)
        self.assertEqual(json.loads(prompt)["пожелания"], self.payload["wishes"])
        self.assertEqual(json.loads(prompt)["количество_скриншотов"], 6)
        self.assertIn("исходными условиями и числами", instructions)
        self.assertIn("Комментарий преподавателя", instructions)
        self.assertFalse(Exercise.objects.exists())
        self.assertFalse((Path(self.temp.name) / "uploads").exists())
        self.student.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual((self.student.opening_balance_rub, self.payment.amount_rub), (500, 1500))

    @patch("assistant.views.get_provider")
    def test_large_valid_screenshot_uses_multipart_and_is_compressed_locally(self, factory):
        factory.return_value.complete.return_value = json.dumps(self.task)
        output = io.BytesIO()
        Image.new("RGB", (1000, 1000), "white").save(output, format="PNG", compress_level=0)
        self.assertGreater(len(output.getvalue()), 1_000_000)
        response = self.generate([SimpleUploadedFile("large.png", output.getvalue(), content_type="image/png")])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertLess(len(factory.return_value.complete.call_args.kwargs["images"][0][1]), len(output.getvalue()))

    @patch("assistant.views.get_provider")
    def test_screenshots_work_for_school(self, factory):
        factory.return_value.complete.return_value = json.dumps(self.task)
        school = SchoolClass.objects.create(name="7А", subject="Алгебра")
        payload = {key: value for key, value in self.payload.items() if key != "student_id"}
        response = self.generate([self.screenshot()], {**payload, "class_id": str(school.id), "grade": 7})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["class_id"], str(school.id))

    @patch("assistant.views.get_provider")
    def test_invalid_uploads_are_rejected_before_calling_provider(self, factory):
        cases = [([self.screenshot() for _ in range(7)], self.payload),
                 ([SimpleUploadedFile("fake.png", b"not an image")], self.payload),
                 ([self.screenshot()], {**self.payload, "mode": "source"})]
        for files, payload in cases:
            with self.subTest(mode=payload["mode"], files=len(files)):
                self.assertEqual(self.generate(files, payload).status_code, 400)
        factory.assert_not_called()

    @patch("assistant.views.get_provider")
    def test_empty_image_result_is_reported_without_inventing_a_task(self, factory):
        factory.return_value.complete.return_value = '{"exercises": []}'
        response = self.generate([self.screenshot()])
        self.assertEqual(response.status_code, 422)
        self.assertIn("не осталось", response.json()["error"])
        self.assertFalse(Exercise.objects.exists())

    @patch("assistant.views.get_provider")
    def test_continuation_retries_a_duplicate_and_passes_previous_tasks(self, factory):
        factory.return_value.complete.side_effect = [json.dumps(self.task), json.dumps({"exercises": [{
            "title": "Другое уравнение", "prompt": "Решите $3x=12$.", "answer": "$x=4$."}]})]
        previous = "Решите $2x=6$."
        response = self.generate([self.screenshot()], {**self.payload, "existing_tasks": [previous]})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(factory.return_value.complete.call_count, 2)
        retry = factory.return_value.complete.call_args.args[1]
        self.assertIn(previous, retry)
        self.assertIn("повторено", retry)

    def test_images_are_bounded_and_input_limits_are_checked(self):
        images = prepare_screenshots([self.screenshot(size=(3000, 1000))])
        with Image.open(io.BytesIO(images[0][1])) as image:
            self.assertEqual(image.size, (2400, 800))
        with self.assertRaisesRegex(ValueError, "10 МБ"):
            prepare_screenshots([SimpleNamespace(size=11 * 1024 * 1024)])
        with self.assertRaisesRegex(ValueError, "30 МБ"):
            prepare_screenshots([SimpleNamespace(size=6 * 1024 * 1024) for _ in range(6)])

    def test_malformed_multipart_parameters_are_rejected(self):
        for payload in ("bad json", "[]", ""):
            with self.subTest(payload=payload):
                response = self.client.post("/api/assistant/generate", {"payload": payload, "screenshots": self.screenshot()})
                self.assertEqual(response.status_code, 400)


class ProviderImageInputTests(TestCase):
    def test_images_use_image_parts_with_their_real_mime(self):
        parts = user_content("Перенеси задания", images=[("image/png", b"png"), ("image/jpeg", b"jpeg")])
        self.assertEqual(parts[1]["text"], "Скриншот 1")
        self.assertEqual(parts[2], {"type": "input_image", "detail": "high",
                                    "image_url": "data:image/png;base64," + base64.b64encode(b"png").decode()})
        self.assertTrue(parts[4]["image_url"].startswith("data:image/jpeg;base64,"))

    @patch("assistant.chatgpt_auth.credentials")
    @patch("assistant.providers.urlopen")
    def test_both_providers_send_images(self, urlopen, credentials):
        credentials.return_value = {"model": "test-model", "access_token": "test-token"}
        cases = [(OpenAIResponsesProvider("test-key", "test-model"), b'{"output":[{"type":"message","content":[{"type":"output_text","text":"ok"}]}]}'),
                 (ChatGPTPlanProvider(), b'data: {"type":"response.output_text.delta","delta":"ok"}\n\ndata: {"type":"response.completed"}\n\n')]
        for provider, response in cases:
            with self.subTest(provider=type(provider).__name__):
                urlopen.return_value.__enter__.return_value = io.BytesIO(response)
                self.assertEqual(provider.complete("Instructions", "Prompt", images=[("image/png", b"test")]), "ok")
                request = urlopen.call_args.args[0]
                payload = json.loads(request.data)
                self.assertEqual(payload["input"][0]["content"][2]["type"], "input_image")
