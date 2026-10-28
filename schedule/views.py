"""Local scheduling page and JSON API."""

from datetime import date, datetime, timedelta

from django.db import transaction
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from students.models import Student, Subject
from students.views import api_errors, body, fail, number

from .models import Lesson, LessonComment, WeeklyRule
from .notes import note_fields, serialize_note, sort_notes
from .services import (
    change_series, check_collision, check_one_off_future_collisions,
    check_rule_collision, end_series, ensure_occurrences,
)


@ensure_csrf_cookie
def schedule_page(request):
    return render(request, "schedule.html")


def parse_date(value, label="Дата"):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"Поле «{label}» содержит некорректную дату") from None


def parse_time(value):
    try:
        result = datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError):
        raise ValueError("Укажите время в формате ЧЧ:ММ") from None
    return result


def find(model, item_id):
    item = model.objects.filter(id=item_id).first()
    if item is None:
        raise LookupError("Занятие или серия не найдены")
    return item


def student_and_subject(data):
    try:
        student = Student.objects.filter(id=data.get("student_id")).first()
    except (ValidationError, ValueError):
        student = None
    if student is None:
        raise ValueError("Выберите ученика")
    subject_id = data.get("subject_id")
    subject = None
    if subject_id:
        try:
            subject = Subject.objects.filter(id=subject_id, student=student).first()
        except (ValidationError, ValueError):
            subject = None
        if subject is None:
            raise ValueError("Предмет не относится к этому ученику")
    return student, subject


def lesson_fields(data):
    student, subject = student_and_subject(data)
    day = parse_date(data.get("date"))
    time_value = parse_time(data.get("time"))
    duration = number(data.get("duration_min"), "Длительность", 15, 240)
    if time_value.hour * 60 + time_value.minute + duration > 24 * 60:
        raise ValueError("Занятие должно закончиться до полуночи")
    status = data.get("status", "planned")
    if status not in {"planned", "completed", "cancelled"}:
        raise ValueError("Некорректный статус занятия")
    return {
        "student": student, "subject": subject, "date": day,
        "time": time_value, "duration_min": duration, "status": status,
    }


def serialize(lesson):
    rule = lesson.weekly_rule
    return {
        "id": str(lesson.id), "student_id": str(lesson.student_id),
        "student_name": lesson.student.name, "grade": lesson.student.grade,
        "subject_id": str(lesson.subject_id) if lesson.subject_id else "",
        "subject_name": lesson.subject.name if lesson.subject else "Занятие",
        "date": lesson.date.isoformat(), "time": lesson.time.strftime("%H:%M"),
        "duration_min": lesson.duration_min, "status": lesson.status,
        "charged_price_rub": lesson.charged_price_rub,
        "comments": [serialize_note(comment, lesson) for comment in sort_notes(lesson.comments.all())],
        "recurring": bool(rule),
        "weekly_rule_id": str(lesson.weekly_rule_id) if rule else None,
        "source_date": lesson.source_date.isoformat() if lesson.source_date else None,
        "rule": {
            "weekday": rule.weekday, "time": rule.time.strftime("%H:%M"),
            "duration_min": rule.duration_min,
            "student_id": str(rule.student_id),
            "subject_id": str(rule.subject_id) if rule.subject_id else "",
        } if rule else None,
    }


@api_errors
def week_view(request):
    if request.method != "GET":
        return fail("Метод не поддерживается", 405)
    chosen = parse_date(request.GET.get("week", date.today().isoformat()))
    start = chosen - timedelta(days=chosen.weekday())
    end = start + timedelta(days=6)
    ensure_occurrences(start, end)
    lessons = Lesson.objects.filter(date__range=(start, end)).select_related(
        "student", "subject", "weekly_rule"
    ).prefetch_related("comments")
    students = Student.objects.prefetch_related("subjects").order_by("name")
    return JsonResponse({
        "start": start.isoformat(), "end": end.isoformat(),
        "lessons": [serialize(lesson) for lesson in lessons],
        "students": [{
            "id": str(student.id), "name": student.name, "grade": student.grade,
            "status": student.status, "duration_min": student.duration_min,
            "subjects": [{"id": str(subject.id), "name": subject.name}
                         for subject in student.subjects.all()],
        } for student in students],
    })


@api_errors
@transaction.atomic
def lessons_collection(request):
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    data = body(request)
    fields = lesson_fields(data)
    if fields["status"] != "planned":
        raise ValueError("Новое занятие создаётся со статусом «Запланировано»")
    repeat = data.get("repeat_weekly", False)
    if not isinstance(repeat, bool):
        raise ValueError("Некорректный параметр повтора")
    check_collision(fields["date"], fields["time"], fields["duration_min"])
    if repeat:
        weekday = fields["date"].weekday()
        check_rule_collision(weekday, fields["time"], fields["duration_min"], fields["date"])
        check_one_off_future_collisions(weekday, fields["time"], fields["duration_min"], fields["date"])
        rule = WeeklyRule.objects.create(
            student=fields["student"], subject=fields["subject"],
            weekday=weekday, time=fields["time"], duration_min=fields["duration_min"],
            start_date=fields["date"],
        )
        lesson = Lesson.objects.create(**fields, weekly_rule=rule, source_date=fields["date"])
    else:
        lesson = Lesson.objects.create(**fields)
    return JsonResponse(serialize(lesson), status=201)


@api_errors
@transaction.atomic
def lesson_detail(request, lesson_id):
    lesson = find(Lesson, lesson_id)
    if request.method == "PATCH":
        status = body(request).get("status")
        if status not in {"planned", "completed", "cancelled"}:
            raise ValueError("Выберите статус занятия")
        if status != "cancelled" and lesson.status == "cancelled":
            check_collision(lesson.date, lesson.time, lesson.duration_min, lesson.id)
        if status == "completed" and lesson.status != "completed":
            lesson.charged_price_rub = lesson.student.price_rub
        lesson.status = status
        if lesson.weekly_rule_id:
            lesson.is_override = True
        lesson.save()
        return JsonResponse(serialize(lesson))
    if request.method == "PUT":
        previous_status = lesson.status
        previous_student_id = lesson.student_id
        fields = lesson_fields(body(request))
        if previous_student_id != fields["student"].id and lesson.worksheets.exists():
            raise ValueError("У занятия уже есть задания. Сначала перенесите или удалите их, затем меняйте ученика.")
        if fields["status"] != "cancelled":
            check_collision(fields["date"], fields["time"], fields["duration_min"], lesson.id)
        for key, value in fields.items():
            setattr(lesson, key, value)
        if fields["status"] == "completed" and (
            previous_status != "completed" or previous_student_id != fields["student"].id
            or lesson.charged_price_rub is None
        ):
            lesson.charged_price_rub = fields["student"].price_rub
        if lesson.weekly_rule_id:
            lesson.is_override = True
        lesson.save()
        if previous_student_id != lesson.student_id:
            lesson.comments.update(student=lesson.student)
        return JsonResponse(serialize(lesson))
    if request.method == "DELETE":
        if lesson.weekly_rule_id:
            lesson.status = "cancelled"
            lesson.is_override = True
            lesson.save(update_fields=["status", "is_override", "updated_at"])
        else:
            lesson.delete()
        return JsonResponse({"ok": True})
    return fail("Метод не поддерживается", 405)


@api_errors
@transaction.atomic
def lesson_comments(request, lesson_id):
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    lesson = find(Lesson, lesson_id)
    comment = LessonComment.objects.create(student=lesson.student, lesson=lesson, **note_fields(body(request)))
    if lesson.weekly_rule_id and not lesson.is_override:
        lesson.is_override = True
        lesson.save(update_fields=["is_override", "updated_at"])
    return JsonResponse(serialize_note(comment, lesson), status=201)


@api_errors
def comment_detail(request, comment_id):
    comment = LessonComment.objects.filter(id=comment_id).first()
    if comment is None:
        raise LookupError("Комментарий не найден")
    if request.method == "PUT":
        for key, value in note_fields(body(request)).items():
            setattr(comment, key, value)
        comment.save()
        return JsonResponse(serialize_note(comment))
    if request.method == "DELETE":
        comment.delete()
        return JsonResponse({"ok": True})
    return fail("Метод не поддерживается", 405)


@api_errors
def rule_detail(request, rule_id):
    rule = find(WeeklyRule, rule_id)
    if request.method == "PUT":
        data = body(request)
        from_date = parse_date(data.get("from_date"), "Дата начала изменений")
        student, subject = student_and_subject(data)
        weekday = number(data.get("weekday"), "День недели", 0, 6)
        time_value = parse_time(data.get("time"))
        duration = number(data.get("duration_min"), "Длительность", 15, 240)
        if time_value.hour * 60 + time_value.minute + duration > 24 * 60:
            raise ValueError("Занятие должно закончиться до полуночи")
        new_rule = change_series(
            rule, from_date, student=student, subject=subject,
            weekday=weekday, time_value=time_value, duration=duration,
        )
        return JsonResponse({"ok": True, "rule_id": str(new_rule.id)})
    if request.method == "DELETE":
        end_series(rule, parse_date(body(request).get("from_date"), "Дата завершения"))
        return JsonResponse({"ok": True})
    return fail("Метод не поддерживается", 405)
