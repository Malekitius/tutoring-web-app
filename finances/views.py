"""Payment ledger and lesson-based balances for the local tutor dashboard."""

import csv
import json
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from schedule.models import Lesson
from schedule.services import ensure_occurrences
from schedule.views import parse_date
from students.models import Student
from students.views import api_errors, body, fail, number, text

from .models import Payment
from .portability import export_document, import_document, parse_document, preview_document


@ensure_csrf_cookie
def finances_page(request):
    return render(request, "finances.html")


def student_from_id(value):
    try:
        student = Student.objects.filter(id=value).first()
    except (ValidationError, ValueError):
        student = None
    if student is None:
        raise ValueError("Выберите ученика")
    return student


def payment_fields(data):
    return {
        "student": student_from_id(data.get("student_id")),
        "paid_on": parse_date(data.get("paid_on"), "Дата оплаты"),
        "amount_rub": number(data.get("amount_rub"), "Сумма", 1, 100_000_000),
        "note": text(data.get("note", ""), "Комментарий", 500),
    }


def serialize_payment(payment):
    return {
        "id": str(payment.id), "student_id": str(payment.student_id),
        "student_name": payment.student.name, "grade": payment.student.grade,
        "paid_on": payment.paid_on.isoformat(), "amount_rub": payment.amount_rub,
        "note": payment.note,
    }


def balance_color(balance, price):
    if price <= 0:
        return ("danger", 0) if balance < 0 else ("no_price", None)
    remaining = max(0, balance // price)
    return ("danger" if remaining == 0 else "warning" if remaining <= 2 else "healthy"), remaining


@api_errors
def dashboard(request):
    if request.method != "GET":
        return fail("Метод не поддерживается", 405)
    today = timezone.localdate()
    start = parse_date(request.GET.get("start", today.replace(day=1).isoformat()), "Начало периода")
    end = parse_date(request.GET.get("end", today.isoformat()), "Конец периода")
    if end < start:
        raise ValueError("Конец периода должен быть не раньше начала")
    if end - start > timedelta(days=3650):
        raise ValueError("Выберите период не длиннее 10 лет")

    ensure_occurrences(start, end)
    period_lessons = list(Lesson.objects.filter(date__range=(start, end)).select_related("student"))
    period_payments = list(Payment.objects.filter(paid_on__range=(start, end)).select_related("student"))
    all_payments = dict(Payment.objects.values_list("student_id").annotate(total=Sum("amount_rub")))
    all_charges = dict(Lesson.objects.filter(status="completed").values_list("student_id").annotate(
        total=Sum(Coalesce("charged_price_rub", "student__price_rub"))
    ))

    students = []
    for student in Student.objects.order_by("status", "name", "grade"):
        paid = all_payments.get(student.id) or 0
        charged = all_charges.get(student.id) or 0
        balance = student.opening_balance_rub + paid - charged
        color, remaining = balance_color(balance, student.price_rub)
        students.append({
            "id": str(student.id), "name": student.name, "grade": student.grade,
            "status": student.status, "price_rub": student.price_rub,
            "opening_balance_rub": student.opening_balance_rub,
            "paid_rub": paid, "charged_rub": charged, "balance_rub": balance,
            "remaining_lessons": remaining, "balance_state": color,
        })

    completed = [lesson for lesson in period_lessons if lesson.status == "completed"]
    planned = [lesson for lesson in period_lessons if lesson.status == "planned"]
    earned = sum(lesson.charged_price_rub if lesson.charged_price_rub is not None
                 else lesson.student.price_rub for lesson in completed)
    forecast = earned + sum(lesson.student.price_rub for lesson in planned)
    return JsonResponse({
        "start": start.isoformat(), "end": end.isoformat(),
        "summary": {
            "received_rub": sum(payment.amount_rub for payment in period_payments),
            "payment_count": len(period_payments),
            "completed_count": len(completed),
            "earned_rub": earned,
            "forecast_rub": forecast,
            "planned_count": len(planned),
        },
        "students": students,
        "payments": [serialize_payment(payment) for payment in period_payments],
    })


@api_errors
def payments_collection(request):
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    payment = Payment.objects.create(**payment_fields(body(request)))
    return JsonResponse(serialize_payment(payment), status=201)


@api_errors
def payment_detail(request, payment_id):
    payment = Payment.objects.filter(id=payment_id).first()
    if payment is None:
        raise LookupError("Внесение не найдено")
    if request.method == "PUT":
        for key, value in payment_fields(body(request)).items():
            setattr(payment, key, value)
        payment.save()
        return JsonResponse(serialize_payment(payment))
    if request.method == "DELETE":
        payment.delete()
        return JsonResponse({"ok": True})
    return fail("Метод не поддерживается", 405)


@api_errors
def opening_balance(request, student_id):
    if request.method != "PUT":
        return fail("Метод не поддерживается", 405)
    student = Student.objects.filter(id=student_id).first()
    if student is None:
        raise LookupError("Ученик не найден")
    student.opening_balance_rub = number(
        body(request).get("opening_balance_rub"), "Начальный остаток", -100_000_000, 100_000_000
    )
    student.save(update_fields=["opening_balance_rub", "updated_at"])
    return JsonResponse({"ok": True, "opening_balance_rub": student.opening_balance_rub})


@api_errors
def finance_export(request):
    if request.method != "GET":
        return fail("Метод не поддерживается", 405)
    result = HttpResponse(json.dumps(export_document(), ensure_ascii=False, indent=2) + "\n", content_type="application/json; charset=utf-8")
    result["Content-Disposition"] = 'attachment; filename="finances-v1.json"'
    return result


def csv_cell(value):
    value = str(value)
    return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value


@api_errors
def finance_export_csv(request):
    if request.method != "GET":
        return fail("Метод не поддерживается", 405)
    today = timezone.localdate()
    start = parse_date(request.GET.get("start", today.replace(day=1).isoformat()), "Начало периода")
    end = parse_date(request.GET.get("end", today.isoformat()), "Конец периода")
    if end < start or end - start > timedelta(days=3650):
        raise ValueError("Выберите период не длиннее 10 лет")
    rows = []
    for item in Payment.objects.filter(paid_on__range=(start, end)).select_related("student"):
        rows.append((item.paid_on, "Внесение", item.student.name, item.student_id, item.id,
                     item.amount_rub, "", item.note))
    for item in Lesson.objects.filter(status="completed", date__range=(start, end)).select_related("student"):
        amount = item.charged_price_rub if item.charged_price_rub is not None else item.student.price_rub
        rows.append((item.date, "Проведённое занятие", item.student.name, item.student_id, item.id,
                     "", amount, ""))
    rows.sort(key=lambda row: (row[0], row[1], str(row[4])))
    result = HttpResponse(content_type="text/csv; charset=utf-8")
    result["Content-Disposition"] = f'attachment; filename="finances-{start}-{end}.csv"'
    result.write("\ufeff")
    writer = csv.writer(result, delimiter=";")
    writer.writerow(["Дата", "Операция", "Ученик", "ID ученика", "ID записи", "Получено, ₽", "Начислено, ₽", "Комментарий"])
    for row in rows:
        writer.writerow([row[0].isoformat(), row[1], csv_cell(row[2]), str(row[3]), str(row[4]), row[5], row[6], csv_cell(row[7])])
    return result


@api_errors
def finance_import(request):
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    document = parse_document(request.FILES.get("file"))
    if request.GET.get("dry_run") == "1":
        return JsonResponse(preview_document(document))
    if request.POST.get("confirm") != "IMPORT":
        return fail("Подтвердите загрузку финансовых данных")
    return JsonResponse(import_document(document))
