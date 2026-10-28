import json
import csv
import io
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from schedule.models import Lesson
from students.models import Student

from .models import Payment


class FinanceTests(TestCase):
    def setUp(self):
        self.student = Student.objects.create(name="Тестовый ученик", grade=6, price_rub=1000)

    def send(self, method, path, payload):
        return getattr(self.client, method)(path, data=json.dumps(payload), content_type="application/json")

    def lesson(self, day, time="16:00"):
        response = self.send("post", "/api/schedule/lessons", {
            "student_id": str(self.student.id), "date": day,
            "time": time, "duration_min": 60,
        })
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["id"]

    def dashboard(self, start="2026-10-19", end="2026-10-25"):
        response = self.client.get(f"/api/finances/?start={start}&end={end}")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_payment_balance_outcome_and_price_snapshot(self):
        lesson_id = self.lesson("2026-10-20")
        self.student.opening_balance_rub = 300
        self.student.save(update_fields=["opening_balance_rub"])
        payment = self.send("post", "/api/finances/payments", {
            "student_id": str(self.student.id), "paid_on": "2026-10-20",
            "amount_rub": 2700, "note": "Аванс",
        })
        self.assertEqual(payment.status_code, 201)
        held = self.send("patch", f"/api/schedule/lessons/{lesson_id}", {"status": "completed"})
        self.assertEqual(held.status_code, 200)
        self.assertEqual(held.json()["charged_price_rub"], 1000)
        self.student.price_rub = 1500
        self.student.save(update_fields=["price_rub"])
        summary = self.dashboard()
        self.assertEqual(summary["summary"]["received_rub"], 2700)
        self.assertEqual(summary["summary"]["earned_rub"], 1000)
        self.assertEqual(summary["students"][0]["balance_rub"], 2000)
        self.assertEqual(summary["students"][0]["remaining_lessons"], 1)
        self.assertEqual(summary["students"][0]["balance_state"], "warning")

        missed_id = self.lesson("2026-10-22")
        missed = self.send("patch", f"/api/schedule/lessons/{missed_id}", {"status": "cancelled"})
        self.assertEqual(missed.status_code, 200)
        self.assertEqual(self.dashboard()["summary"]["earned_rub"], 1000)
        self.assertEqual(Lesson.objects.get(id=lesson_id).charged_price_rub, 1000)

    def test_period_receipts_and_payment_correction(self):
        first = self.send("post", "/api/finances/payments", {
            "student_id": str(self.student.id), "paid_on": "2026-10-20", "amount_rub": 1000,
        })
        second = self.send("post", "/api/finances/payments", {
            "student_id": str(self.student.id), "paid_on": "2026-11-03", "amount_rub": 2000,
        })
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(self.dashboard()["summary"]["received_rub"], 1000)
        self.assertEqual(self.dashboard("2026-10-01", "2026-11-30")["summary"]["received_rub"], 3000)
        edited = self.send("put", f"/api/finances/payments/{first.json()['id']}", {
            "student_id": str(self.student.id), "paid_on": "2026-10-20", "amount_rub": 1500,
        })
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(self.dashboard()["summary"]["received_rub"], 1500)
        self.assertEqual(self.send("delete", f"/api/finances/payments/{second.json()['id']}", {}).status_code, 200)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(self.dashboard()["students"][0]["balance_rub"], 1500)

    def test_forecast_and_red_balance(self):
        planned_id = self.lesson("2026-10-20")
        done_id = self.lesson("2026-10-21")
        cancelled_id = self.lesson("2026-10-22")
        self.send("patch", f"/api/schedule/lessons/{done_id}", {"status": "completed"})
        self.send("patch", f"/api/schedule/lessons/{cancelled_id}", {"status": "cancelled"})
        summary = self.dashboard()
        self.assertEqual(summary["summary"]["forecast_rub"], 2000)
        self.assertEqual(summary["summary"]["earned_rub"], 1000)
        self.assertEqual(summary["students"][0]["balance_rub"], -1000)
        self.assertEqual(summary["students"][0]["balance_state"], "danger")
        self.assertEqual(summary["students"][0]["remaining_lessons"], 0)
        self.assertEqual(Lesson.objects.get(id=planned_id).status, "planned")

    def test_opening_balance_is_not_received_money(self):
        response = self.send("put", f"/api/finances/students/{self.student.id}/opening-balance", {
            "opening_balance_rub": 2500,
        })
        self.assertEqual(response.status_code, 200)
        summary = self.dashboard()
        self.assertEqual(summary["summary"]["received_rub"], 0)
        self.assertEqual(summary["students"][0]["balance_rub"], 2500)
        self.assertEqual(summary["students"][0]["remaining_lessons"], 2)
        self.assertEqual(summary["students"][0]["balance_state"], "warning")

    def test_debt_is_red_even_before_setting_price(self):
        self.student.price_rub = 0
        self.student.opening_balance_rub = -500
        self.student.save(update_fields=["price_rub", "opening_balance_rub"])
        student = self.dashboard()["students"][0]
        self.assertEqual(student["balance_state"], "danger")
        self.assertEqual(student["balance_rub"], -500)

    def test_student_with_financial_history_cannot_be_deleted(self):
        self.send("post", "/api/finances/payments", {
            "student_id": str(self.student.id), "paid_on": "2026-10-20", "amount_rub": 1000,
        })
        response = self.send("delete", f"/api/students/{self.student.id}", {})
        self.assertEqual(response.status_code, 409)

    def test_financial_json_preview_import_is_idempotent(self):
        lesson_id = self.lesson("2026-10-20")
        self.send("patch", f"/api/schedule/lessons/{lesson_id}", {"status": "completed"})
        self.student.opening_balance_rub = 400
        self.student.save(update_fields=["opening_balance_rub"])
        payment = Payment.objects.create(student=self.student, paid_on="2026-10-20", amount_rub=2500, note="Аванс")
        payment_id = payment.id
        response = self.client.get("/api/finances/export")
        self.assertEqual(response.status_code, 200)
        exported = response.content
        self.assertEqual(json.loads(exported)["version"], 1)

        payment.delete()
        self.student.opening_balance_rub = 0
        self.student.save(update_fields=["opening_balance_rub"])
        def uploaded():
            return SimpleUploadedFile("finances.json", exported, content_type="application/json")

        preview = self.client.post("/api/finances/import?dry_run=1", {"file": uploaded()})
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(preview.json()["payments_new"], 1)
        self.assertEqual(preview.json()["students_updated"], 1)
        self.assertTrue(preview.json()["can_import"])
        imported = self.client.post("/api/finances/import", {"file": uploaded(), "confirm": "IMPORT"})
        self.assertEqual(imported.status_code, 200, imported.content)
        self.assertEqual(Payment.objects.get(id=payment_id).amount_rub, 2500)
        self.student.refresh_from_db()
        self.assertEqual(self.student.opening_balance_rub, 400)
        again = self.client.post("/api/finances/import?dry_run=1", {"file": uploaded()}).json()
        self.assertEqual((again["payments_new"], again["payments_updated"], again["students_updated"]), (0, 0, 0))

    def test_financial_import_requires_existing_lessons(self):
        lesson_id = self.lesson("2026-10-20")
        self.send("patch", f"/api/schedule/lessons/{lesson_id}", {"status": "completed"})
        exported = self.client.get("/api/finances/export").content
        Lesson.objects.filter(id=lesson_id).delete()
        file = lambda: SimpleUploadedFile("finances.json", exported, content_type="application/json")
        preview = self.client.post("/api/finances/import?dry_run=1", {"file": file()}).json()
        self.assertFalse(preview["can_import"])
        self.assertEqual(preview["missing_lessons"], [lesson_id])
        self.assertEqual(self.client.post("/api/finances/import", {"file": file(), "confirm": "IMPORT"}).status_code, 400)

    def test_financial_csv_contains_period_ledger(self):
        self.student.name = "=FORMULA()"
        self.student.save(update_fields=["name"])
        self.lesson("2026-10-20")
        Payment.objects.create(student=self.student, paid_on="2026-10-20", amount_rub=750)
        response = self.client.get("/api/finances/export/csv?start=2026-10-19&end=2026-10-25")
        self.assertEqual(response.status_code, 200)
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(rows[0][0], "Дата")
        self.assertEqual(rows[1][5], "750")
        self.assertEqual(rows[1][2], "'=FORMULA()")
        self.assertTrue(Student.objects.filter(id=self.student.id).exists())
        self.assertEqual(Payment.objects.count(), 1)
