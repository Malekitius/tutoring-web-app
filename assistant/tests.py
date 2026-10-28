import json
import io
import ssl
import tempfile
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

from django.test import Client, TestCase

from assignments.models import Exercise, Worksheet, WorksheetItem
from assignments.pdf_export import format_text
from finances.models import Payment
from schedule.models import Lesson, LessonComment
from students.models import Student, Subject, Topic

from .context import student_context
from . import chatgpt_auth
from .https import verified_context
from .providers import ChatGPTPlanProvider, ProviderError


class AssistantWorkflowTest(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.get("/")
        self.csrf = {"HTTP_X_CSRFTOKEN": self.client.cookies["csrftoken"].value}
        self.student = Student.objects.create(name="Тестовый ученик", grade=7, goal="Повторить уравнения",
                                              price_rub=2500, opening_balance_rub=5000)
        self.subject = Subject.objects.create(student=self.student, name="Математика", goal="Уверенно решать задачи")
        Topic.objects.create(subject=self.subject, title="Линейные уравнения", mastery=1, notes="Нужна практика")
        self.lesson = Lesson.objects.create(student=self.student, subject=self.subject, date="2026-10-20",
                                            time="16:00", status="completed", charged_price_rub=2500)
        LessonComment.objects.create(student=self.student, lesson=self.lesson, body="Ошибки в уравнениях")
        LessonComment.objects.create(student=self.student, body="Оплата 2500 рублей")
        Payment.objects.create(student=self.student, paid_on="2026-10-20", amount_rub=2500)

    def post(self, path, payload):
        return self.client.post(path, data=json.dumps(payload), content_type="application/json", **self.csrf)

    def test_context_omits_money_and_masks_financial_note(self):
        context = student_context(self.student)
        serialized = json.dumps(context, ensure_ascii=False)
        self.assertNotIn("2500", serialized)
        self.assertNotIn("5000", serialized)
        self.assertNotIn("Оплата", serialized)
        self.assertIn("[финансовые сведения скрыты]", serialized)
        self.assertIn("Линейные уравнения", serialized)

    @patch("assistant.views.get_provider")
    def test_question_reads_teaching_data_without_changing_finances(self, provider_factory):
        provider = Mock()
        provider.complete.return_value = "Стоит повторить линейные уравнения (занятие 20 октября)."
        provider_factory.return_value = provider
        response = self.post(f"/api/assistant/students/{self.student.id}/ask", {"question": "Что повторить?"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("линейные уравнения", response.json()["answer"])
        prompt = provider.complete.call_args.args[1]
        self.assertIn("Линейные уравнения", prompt)
        self.assertNotIn("2500", prompt)
        self.assertEqual(Payment.objects.get(student=self.student).amount_rub, 2500)
        self.student.refresh_from_db()
        self.lesson.refresh_from_db()
        self.assertEqual(self.student.price_rub, 2500)
        self.assertEqual(self.lesson.charged_price_rub, 2500)

    @patch("assistant.views.get_provider")
    def test_general_question_needs_no_student(self, provider_factory):
        provider_factory.return_value.complete.return_value = "Дробь показывает часть целого."
        response = self.post("/api/assistant/ask", {"question": "Как объяснить школьнику, что такое дробь?"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("часть целого", response.json()["answer"])
        prompt = json.loads(provider_factory.return_value.complete.call_args.args[1])
        self.assertNotIn("учебные_данные", prompt)
        provider_factory.return_value.complete.return_value = "Цена зависит от рынка."
        price = self.post("/api/assistant/ask", {"question": "Сколько стоит доллар?"})
        self.assertEqual(price.status_code, 200)
        self.assertEqual(price.json()["answer"], "Цена зависит от рынка.")

    @patch("assistant.views.get_provider")
    def test_group_question_uses_learning_data_without_money(self, provider_factory):
        provider_factory.return_value.complete.return_value = "Повторите уравнения."
        response = self.post("/api/assistant/ask", {"question": "Какие темы требуют внимания у моих учеников?"})
        self.assertEqual(response.status_code, 200)
        prompt = provider_factory.return_value.complete.call_args.args[1]
        self.assertIn("Тестовый ученик", prompt)
        self.assertIn("Линейные уравнения", prompt)
        self.assertNotIn("2500", prompt)

    @patch("assistant.views.get_provider")
    def test_money_question_uses_local_ledger_without_changing_it(self, provider_factory):
        response = self.post("/api/assistant/ask", {"question": "Сколько заработал на Тестовый ученик?", "period": "custom", "start": "2026-10-01", "end": "2026-10-31"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["financial_report"]["earned_rub"], 2500)
        self.assertEqual(response.json()["financial_report"]["received_rub"], 2500)
        self.assertEqual(response.json()["financial_report"]["balance_rub"], 5000)
        self.assertIn("2 500 ₽", response.json()["answer"])
        provider_factory.assert_not_called()
        self.assertEqual(Payment.objects.get(student=self.student).amount_rub, 2500)
        self.student.refresh_from_db()
        self.lesson.refresh_from_db()
        self.assertEqual(self.student.price_rub, 2500)
        self.assertEqual(self.lesson.charged_price_rub, 2500)

    @patch("assistant.finance.timezone.localdate", return_value=date(2026, 10, 23))
    def test_finance_period_and_received_are_distinct_from_earned(self, _today):
        Payment.objects.create(student=self.student, paid_on="2026-09-05", amount_rub=3000)
        result = self.post("/api/assistant/ask", {"student_id": str(self.student.id), "question": "Сколько получил в этом месяце?"})
        self.assertEqual(result.status_code, 200)
        self.assertIn("получено 2 500 ₽", result.json()["answer"])
        self.assertEqual(result.json()["financial_report"]["start"], "2026-10-01")
        previous = self.post("/api/assistant/ask", {"student_id": str(self.student.id), "question": "Сколько получил за прошлый месяц?"})
        self.assertEqual(previous.json()["financial_report"]["received_rub"], 3000)
        self.assertEqual(previous.json()["financial_report"]["earned_rub"], 0)

    def test_longer_student_name_wins_when_names_overlap(self):
        other = Student.objects.create(name="Очень Тестовый ученик", grade=8, price_rub=3000)
        Payment.objects.create(student=other, paid_on="2026-10-20", amount_rub=7000)
        result = self.post("/api/assistant/ask", {"question": "Сколько получил Очень Тестовый ученик?",
                                                   "period": "custom", "start": "2026-10-01", "end": "2026-10-31"})
        self.assertEqual(result.json()["financial_report"]["received_rub"], 7000)
        self.assertEqual(result.json()["financial_report"]["scope"], "student")
        inflected = self.post("/api/assistant/ask", {"question": "Сколько получил от Очень Тестового ученика?",
                                                      "period": "custom", "start": "2026-10-01", "end": "2026-10-31"})
        self.assertEqual(inflected.json()["financial_report"]["received_rub"], 7000)

    def test_financial_period_is_read_from_question(self):
        month = self.post("/api/assistant/ask", {"question": "Сколько получил от Тестового ученика за октябрь 2026?"})
        self.assertEqual(month.status_code, 200)
        self.assertEqual(month.json()["financial_report"]["received_rub"], 2500)
        self.assertEqual(month.json()["financial_report"]["start"], "2026-10-01")
        interval = self.post("/api/assistant/ask", {"question": "Сколько заработал на Тестовом ученике с 1 по 15 октября 2026?"})
        self.assertEqual(interval.status_code, 200)
        self.assertEqual(interval.json()["financial_report"]["end"], "2026-10-15")
        self.assertEqual(interval.json()["financial_report"]["earned_rub"], 0)
        two_months = self.post("/api/assistant/ask", {"question": "Сколько получил от Тестового ученика с 1 сентября по 25 октября 2026?"})
        self.assertEqual(two_months.status_code, 200)
        self.assertEqual(two_months.json()["financial_report"]["start"], "2026-09-01")
        self.assertEqual(two_months.json()["financial_report"]["end"], "2026-10-25")

    def test_comparison_question_uses_only_named_students(self):
        other = Student.objects.create(name="Другой ученик", grade=6, price_rub=2000)
        Payment.objects.create(student=other, paid_on="2026-10-21", amount_rub=4000)
        response = self.post("/api/assistant/ask", {"question": "Сравни поступления Тестового ученика и Другого ученика за октябрь 2026"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["financial_report"]["scope"], "selected")
        self.assertEqual(response.json()["financial_report"]["received_rub"], 6500)
        self.assertIn("Другой ученик", response.json()["answer"])

    def test_widget_is_on_every_page_and_standalone_page_is_removed(self):
        for path in ["/", "/schedule/", "/assignments/", "/finances/"]:
            page = self.client.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, 'id="assistant-widget"')
            self.assertNotContains(page, 'href="/assistant/"')
        self.assertContains(self.client.get("/assignments/"), 'data-tab="generator"')
        self.assertNotContains(self.client.get("/"), 'name="student_id"')
        self.assertNotContains(self.client.get("/"), 'name="period"')
        self.assertEqual(self.client.get("/assistant/").status_code, 404)

    @patch("assistant.views.get_provider")
    def test_generate_edit_and_explicit_accept_creates_only_assignments(self, provider_factory):
        provider = Mock()
        provider.complete.return_value = json.dumps({"exercises": [{
            "title": "Уравнение", "prompt": "Решите $2x+3=7$.", "answer": "$x=2$."
        }]})
        provider_factory.return_value = provider
        generated = self.post("/api/assistant/generate", {
            "student_id": str(self.student.id), "subject": "Математика", "topic": "Уравнения",
            "difficulty": 2, "count": 1,
        })
        self.assertEqual(generated.status_code, 200)
        self.assertEqual(Exercise.objects.count(), 0)
        draft = generated.json()["exercises"][0]
        draft["prompt"] = "Решите $2x+3=7$ и проверьте ответ."
        saved = self.post("/api/assistant/accept", {
            "student_id": str(self.student.id), "destination": "homework", "title": "Уравнения",
            "exercises": [draft],
        })
        self.assertEqual(saved.status_code, 201)
        self.assertEqual(Exercise.objects.count(), 1)
        self.assertEqual(Worksheet.objects.count(), 1)
        self.assertEqual(WorksheetItem.objects.get().prompt, draft["prompt"])
        self.assertEqual(Payment.objects.get(student=self.student).amount_rub, 2500)
        self.student.refresh_from_db()
        self.assertEqual(self.student.opening_balance_rub, 5000)

    @patch("assistant.views.get_provider")
    def test_mixed_difficulty_generation_and_accept(self, provider_factory):
        def tasks(prefix, count):
            return [{"title": f"{prefix} {index}", "prompt": f"Решите ${index}+1$.", "answer": f"${index + 1}$."}
                    for index in range(count)]
        provider_factory.return_value.complete.return_value = json.dumps({"groups": {
            "1": tasks("Базовая", 5), "2": tasks("Средняя", 2), "4": tasks("Олимпиадная", 1),
        }})
        generated = self.post("/api/assistant/generate", {
            "student_id": str(self.student.id), "subject": "Математика", "topic": "Дроби",
            "difficulty_counts": {"1": 5, "2": 2, "3": 0, "4": 1},
        })
        self.assertEqual(generated.status_code, 200)
        exercises = generated.json()["exercises"]
        self.assertEqual([row["difficulty"] for row in exercises], [1] * 5 + [2] * 2 + [4])
        saved = self.post("/api/assistant/accept", {"student_id": str(self.student.id),
                                                      "destination": "library", "exercises": exercises})
        self.assertEqual(saved.status_code, 201)
        self.assertEqual(Exercise.objects.count(), 8)
        self.assertEqual(Payment.objects.get(student=self.student).amount_rub, 2500)

    @patch("assistant.views.get_provider")
    def test_mixed_difficulty_rejects_wrong_model_distribution(self, provider_factory):
        provider_factory.return_value.complete.return_value = json.dumps({"groups": {"1": [{"title": "А", "prompt": "Решите $x=1$.", "answer": "$x=1$."}]}})
        response = self.post("/api/assistant/generate", {"student_id": str(self.student.id),
                                                          "subject": "Математика", "topic": "Дроби",
                                                          "difficulty_counts": {"1": 1, "2": 1, "3": 0, "4": 0}})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(Exercise.objects.count(), 0)

    @patch("assistant.views.get_provider")
    def test_generation_retries_invalid_latex_for_one_task(self, provider_factory):
        provider_factory.return_value.complete.side_effect = [
            json.dumps({"exercises": [{"title": "Дроби", "prompt": "Вычисли $\\href{x}$.", "answer": "$1$."}]}),
            json.dumps({"exercises": [{"title": "Дроби", "prompt": "Вычисли $\\frac{1}{2}+\\frac{1}{2}$.", "answer": "$1$."}]}),
        ]
        response = self.post("/api/assistant/generate", {
            "student_id": str(self.student.id), "subject": "Математика", "topic": "Дроби",
            "difficulty": 1, "count": 1, "existing_tasks": ["Вычисли $2+2$."],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["exercises"]), 1)
        self.assertEqual(provider_factory.return_value.complete.call_count, 2)
        retry_prompt = provider_factory.return_value.complete.call_args.args[1]
        self.assertIn("\\href", retry_prompt)
        self.assertIn("Вычисли $2+2$.", retry_prompt)
        self.assertEqual(Exercise.objects.count(), 0)

    @patch("assistant.views.get_provider")
    def test_generation_reports_persistent_latex_error(self, provider_factory):
        provider_factory.return_value.complete.return_value = json.dumps({"exercises": [{
            "title": "Дроби", "prompt": "Вычисли $\\href{x}$.", "answer": "$1$."}]})
        response = self.post("/api/assistant/generate", {
            "student_id": str(self.student.id), "subject": "Математика", "topic": "Дроби",
            "difficulty": 1, "count": 1,
        })
        self.assertEqual(response.status_code, 502)
        self.assertIn("\\href", response.json()["error"])
        self.assertEqual(provider_factory.return_value.complete.call_count, 2)

    def test_common_generated_latex_commands_are_pdf_safe(self):
        self.assertIn(r"\boxed{\frac{1}{2}\,x}", format_text(r"Ответ: $\boxed{\frac{1}{2}\,x}$"))

    def test_accept_is_atomic_and_requires_csrf(self):
        good = {"title": "Задача", "prompt": "Решите $x+1=2$", "answer": "$x=1$",
                "subject": "Математика", "topic": "Уравнения", "subtopic": "", "difficulty": 2, "grades": [7]}
        bad = {**good, "title": ""}
        response = self.post("/api/assistant/accept", {"student_id": str(self.student.id),
                                                      "destination": "lesson", "title": "Черновик",
                                                      "exercises": [good, bad]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Exercise.objects.count(), 0)
        self.assertEqual(Worksheet.objects.count(), 0)
        missing_csrf = Client(enforce_csrf_checks=True).post("/api/assistant/accept",
            data=json.dumps({"student_id": str(self.student.id), "destination": "library", "exercises": [good]}),
            content_type="application/json")
        self.assertEqual(missing_csrf.status_code, 403)


class ChatGPTLoginTest(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(chatgpt_auth, "AUTH_PATH", Path(self.temp.name) / "auth.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = Client(enforce_csrf_checks=True)
        self.client.get("/")
        self.csrf = {"HTTP_X_CSRFTOKEN": self.client.cookies["csrftoken"].value}

    def test_login_starts_with_pkce_and_rejects_wrong_state(self):
        started = self.client.post("/api/assistant/auth/start", data="{}", content_type="application/json",
                                   HTTP_HOST="127.0.0.1:8765", SERVER_PORT="8765", **self.csrf)
        self.assertEqual(started.status_code, 200)
        params = parse_qs(urlparse(started.json()["url"]).query)
        self.assertEqual(params["client_id"], ["dynamic_agent_client"])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertEqual(params["redirect_uri"], ["http://127.0.0.1:8765/api/assistant/auth/callback/"])
        self.assertNotIn("access_token", started.json()["url"])
        with patch.object(chatgpt_auth, "_post_form") as exchange:
            callback = self.client.get("/api/assistant/auth/callback/?state=wrong&code=example")
        self.assertEqual(callback.status_code, 302)
        self.assertIn("auth_error", callback["Location"])
        exchange.assert_not_called()
        self.assertFalse(chatgpt_auth._read().get("access_token"))

    @patch("assistant.chatgpt_auth.urlopen")
    def test_token_exchange_reports_http_status_and_safe_code(self, urlopen):
        urlopen.side_effect = HTTPError(
            "https://auth.openai.com/api/accounts/oauth/token", 400, "Bad Request", {},
            io.BytesIO(b'{"error":"invalid_grant","error_description":"private detail"}'),
        )
        with self.assertRaisesRegex(ProviderError, "HTTP 400, код invalid_grant") as error:
            chatgpt_auth._post_form("https://auth.openai.com/api/accounts/oauth/token", {"code": "secret"})
        self.assertNotIn("private detail", str(error.exception))
        self.assertNotIn("secret", str(error.exception))
        context = urlopen.call_args.kwargs["context"]
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    @patch("assistant.chatgpt_auth.urlopen")
    def test_token_exchange_distinguishes_network_error(self, urlopen):
        urlopen.side_effect = URLError("name resolution failed")
        with self.assertRaisesRegex(ProviderError, "Нет соединения с сервером OpenAI"):
            chatgpt_auth._post_form("https://auth.openai.com/api/accounts/oauth/token", {})

    @patch("assistant.chatgpt_auth.jwt.decode")
    @patch("assistant.chatgpt_auth.jwt.PyJWKClient")
    @patch("assistant.chatgpt_auth._get_json")
    @patch("assistant.chatgpt_auth._post_form")
    def test_callback_verifies_jwks_with_trusted_context(self, exchange, get_json, jwks_client, decode):
        started = self.client.post("/api/assistant/auth/start", data="{}", content_type="application/json",
                                   HTTP_HOST="127.0.0.1:8765", SERVER_PORT="8765", **self.csrf)
        params = parse_qs(urlparse(started.json()["url"]).query)
        nonce = self.client.session["assistant_oauth"]["nonce"]
        exchange.return_value = {
            "scope": "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct",
            "access_token": "access", "refresh_token": "refresh", "id_token": "signed-id-token",
        }
        get_json.side_effect = [
            {"jwks_uri": "https://auth.openai.com/.well-known/jwks.json", "issuer": "https://auth.openai.com"},
            {"models": [{"slug": "available-model", "visibility": "list"}]},
        ]
        jwks_client.return_value.get_signing_key_from_jwt.return_value.key = "signing-key"
        decode.return_value = {"nonce": nonce, "sub": "test-account"}
        callback = self.client.get(
            "/api/assistant/auth/callback/",
            {"state": params["state"][0], "code": "test-code", "client_id": "oaiapp_test"},
            HTTP_HOST="127.0.0.1:8765", SERVER_PORT="8765",
        )
        self.assertEqual(callback.status_code, 302)
        self.assertEqual(callback["Location"], "/?connected=1")
        context = jwks_client.call_args.kwargs["ssl_context"]
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertEqual(chatgpt_auth._read()["model"], "available-model")


class PlanProviderTest(TestCase):
    def test_https_context_has_trusted_roots(self):
        self.assertGreater(verified_context().cert_store_stats()["x509_ca"], 0)

    @patch("assistant.providers.urlopen")
    @patch("assistant.chatgpt_auth.credentials")
    def test_stream_requires_completion_and_uses_plan_contract(self, credentials, urlopen):
        credentials.return_value = {"model": "test-model", "access_token": "test-token"}
        events = [
            {"type": "response.output_text.delta", "delta": "Привет"},
            {"type": "response.completed", "response": {}},
        ]
        urlopen.return_value = io.BytesIO("".join(f"data: {json.dumps(event)}\n\n" for event in events).encode())
        self.assertEqual(ChatGPTPlanProvider().complete("Правила", "Вопрос"), "Привет")
        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(payload["store"], False)
        self.assertEqual(payload["stream"], True)
        self.assertEqual(payload["model"], "test-model")
        self.assertIsInstance(urlopen.call_args.kwargs["context"], ssl.SSLContext)
        urlopen.return_value = io.BytesIO(b'data: {"type":"response.output_text.delta","delta":"partial"}\n\n')
        with self.assertRaises(ProviderError):
            ChatGPTPlanProvider().complete("Правила", "Вопрос")
