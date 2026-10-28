"""Versioned financial ledger export and human-confirmed merge by stable IDs."""

import json
import re
import uuid
from datetime import date, datetime, timezone

from django.db import transaction

from schedule.models import Lesson
from students.models import Student

from .models import Payment


FINANCE_FORMAT = "tutoring-web-app.finances"
FINANCE_VERSION = 1
MAX_FINANCE_FILE = 20 * 1024 * 1024


def export_document():
    with transaction.atomic():
        students = [{
            "id": str(item.id), "name": item.name,
            "price_rub": item.price_rub, "opening_balance_rub": item.opening_balance_rub,
        } for item in Student.objects.order_by("id")]
        payments = [{
            "id": str(item.id), "student_id": str(item.student_id),
            "paid_on": item.paid_on.isoformat(), "amount_rub": item.amount_rub, "note": item.note,
        } for item in Payment.objects.order_by("id")]
        completed_lessons = [{
            "id": str(item.id), "student_id": str(item.student_id),
            "date": item.date.isoformat(),
            "charged_price_rub": item.charged_price_rub if item.charged_price_rub is not None else item.student.price_rub,
        } for item in Lesson.objects.filter(status="completed").select_related("student").order_by("id")]
    return {
        "format": FINANCE_FORMAT, "version": FINANCE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "students": students, "payments": payments, "completed_lessons": completed_lessons,
    }


def _uuid(value):
    try:
        return str(uuid.UUID(value)) if isinstance(value, str) else None
    except ValueError:
        return None


def _money(value, minimum, maximum=100_000_000):
    return type(value) is int and minimum <= value <= maximum


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def parse_document(file):
    if not file or file.size > MAX_FINANCE_FILE:
        raise ValueError("Выберите финансовый JSON размером до 20 МБ")
    try:
        document = json.loads(file.read().decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Файл должен содержать корректный JSON") from None
    if not isinstance(document, dict) or set(document) != {
        "format", "version", "created_at", "students", "payments", "completed_lessons"
    } or document["format"] != FINANCE_FORMAT or type(document["version"]) is not int or document["version"] != FINANCE_VERSION:
        raise ValueError("Неподдерживаемый формат финансового файла")
    for key in ("students", "payments", "completed_lessons"):
        if not isinstance(document[key], list) or len(document[key]) > 50_000:
            raise ValueError(f"Неверный раздел файла: {key}")
        ids = set()
        for row in document[key]:
            if not isinstance(row, dict) or not _uuid(row.get("id")) or row["id"] in ids:
                raise ValueError(f"Неверный или повторяющийся ID в разделе {key}")
            ids.add(row["id"])
            if key == "students":
                valid = (set(row) == {"id", "name", "price_rub", "opening_balance_rub"}
                         and isinstance(row["name"], str) and 0 < len(row["name"]) <= 120
                         and _money(row["price_rub"], 0, 1_000_000)
                         and _money(row["opening_balance_rub"], -100_000_000))
            elif key == "payments":
                valid = (set(row) == {"id", "student_id", "paid_on", "amount_rub", "note"}
                         and _uuid(row["student_id"]) and _date(row["paid_on"])
                         and _money(row["amount_rub"], 1)
                         and isinstance(row["note"], str) and len(row["note"]) <= 500)
            else:
                valid = (set(row) == {"id", "student_id", "date", "charged_price_rub"}
                         and _uuid(row["student_id"]) and _date(row["date"])
                         and _money(row["charged_price_rub"], 0))
            if not valid:
                raise ValueError(f"Неверные данные в разделе {key}")
    return document


def preview_document(document):
    incoming_students = document["students"]
    student_ids = [row["id"] for row in incoming_students]
    existing_students = {str(item.id): item for item in Student.objects.filter(id__in=student_ids)}
    existing_payments = {str(item.id): item for item in Payment.objects.filter(
        id__in=[row["id"] for row in document["payments"]]
    )}
    existing_lessons = {str(item.id): item for item in Lesson.objects.filter(
        id__in=[row["id"] for row in document["completed_lessons"]]
    )}
    exported_student_ids = set(student_ids)
    missing_students = sorted(exported_student_ids - set(existing_students))
    conflicts = []
    payment_new = payment_updated = lesson_updated = student_updated = 0
    for row in incoming_students:
        item = existing_students.get(row["id"])
        if item and (item.price_rub != row["price_rub"] or item.opening_balance_rub != row["opening_balance_rub"]):
            student_updated += 1
    for row in document["payments"]:
        if row["student_id"] not in exported_student_ids:
            conflicts.append(f"Внесение {row['id']}: ученик отсутствует в файле")
        item = existing_payments.get(row["id"])
        if item is None:
            payment_new += 1
        elif str(item.student_id) != row["student_id"]:
            conflicts.append(f"Внесение {row['id']}: другой ученик")
        elif (item.paid_on.isoformat(), item.amount_rub, item.note) != (row["paid_on"], row["amount_rub"], row["note"]):
            payment_updated += 1
    missing_lessons = []
    for row in document["completed_lessons"]:
        if row["student_id"] not in exported_student_ids:
            conflicts.append(f"Занятие {row['id']}: ученик отсутствует в файле")
        item = existing_lessons.get(row["id"])
        if item is None:
            missing_lessons.append(row["id"])
        elif str(item.student_id) != row["student_id"] or item.date.isoformat() != row["date"]:
            conflicts.append(f"Занятие {row['id']}: ученик или дата не совпадают")
        elif item.status != "completed" or item.charged_price_rub != row["charged_price_rub"]:
            lesson_updated += 1
    return {
        "students_updated": student_updated, "payments_new": payment_new,
        "payments_updated": payment_updated, "lessons_updated": lesson_updated,
        "missing_students": missing_students, "missing_lessons": missing_lessons,
        "conflicts": conflicts[:20],
        "can_import": not (missing_students or missing_lessons or conflicts),
        "received_rub": sum(row["amount_rub"] for row in document["payments"]),
        "charged_rub": sum(row["charged_price_rub"] for row in document["completed_lessons"]),
    }


@transaction.atomic
def import_document(document):
    preview = preview_document(document)
    if not preview["can_import"]:
        raise ValueError("Импорт невозможен: проверьте отсутствующих учеников, занятия и конфликты")
    for row in document["students"]:
        Student.objects.filter(id=row["id"]).update(
            price_rub=row["price_rub"], opening_balance_rub=row["opening_balance_rub"]
        )
    for row in document["payments"]:
        Payment.objects.update_or_create(
            id=row["id"], defaults={
                "student_id": row["student_id"], "paid_on": row["paid_on"],
                "amount_rub": row["amount_rub"], "note": row["note"],
            }
        )
    for row in document["completed_lessons"]:
        Lesson.objects.filter(id=row["id"]).update(status="completed", charged_price_rub=row["charged_price_rub"])
    return preview
