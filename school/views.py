"""Class cards and the school timetable."""

from datetime import date, timedelta
from functools import wraps

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from schedule.views import parse_date, parse_time
from students.views import body, fail, number, text

from .models import SchoolClass, SchoolLesson, SchoolStudent, SchoolWeeklyRule, SchoolWorksheet
from .services import (
    change_series, check_collision, check_one_off_future_collisions,
    check_rule_collision, end_series, ensure_occurrences,
)


GROUPS = {choice[0] for choice in SchoolStudent.GROUP_CHOICES}
STATUSES = {choice[0] for choice in SchoolLesson.STATUS_CHOICES}


def api_errors(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ValueError as exc:
            return fail(str(exc))
        except LookupError as exc:
            return fail(str(exc), 404)
        except IntegrityError:
            return fail("Такой класс с этим предметом уже существует", 409)
    return wrapped


@ensure_csrf_cookie
def classes_page(request):
    return render(request, "school-classes.html")


@ensure_csrf_cookie
def schedule_page(request):
    return render(request, "school-schedule.html")


@ensure_csrf_cookie
def assignments_page(request):
    return render(request, "school-assignments.html")


def find(model, item_id, label):
    item = model.objects.filter(id=item_id).first()
    if item is None:
        raise LookupError(f"{label} не найден(а)")
    return item


def class_from(data):
    try:
        item = SchoolClass.objects.filter(id=data.get("class_id")).first()
    except (ValidationError, ValueError, TypeError):
        item = None
    if item is None:
        raise ValueError("Выберите класс")
    return item


def class_fields(data):
    return {
        "name": text(data.get("name", ""), "Название класса", 80, True),
        "subject": text(data.get("subject", ""), "Предмет", 80, True),
        "level": text(data.get("level", ""), "Уровень", 80, True),
    }


def student_fields(data):
    group = data.get("group", "mastering")
    if group not in GROUPS:
        raise ValueError("Выберите одну из трёх групп")
    raw_birth = data.get("birth_date") or None
    birth = parse_date(raw_birth, "Дата рождения") if raw_birth else None
    if birth and birth > date.today():
        raise ValueError("Дата рождения не может быть в будущем")
    return {
        "name": text(data.get("name", ""), "Имя ученика", 120, True),
        "group": group,
        "birth_date": birth,
        "comment": text(data.get("comment", ""), "Комментарий", 5000),
    }


def serialize_student(item):
    return {
        "id": str(item.id), "class_id": str(item.school_class_id),
        "name": item.name, "group": item.group,
        "birth_date": item.birth_date.isoformat() if item.birth_date else None,
        "comment": item.comment,
    }


def serialize_class(item, detailed=False):
    result = {
        "id": str(item.id), "name": item.name, "subject": item.subject,
        "level": item.level, "student_count": item.students.count() if detailed else item.student_count,
    }
    if detailed:
        result["students"] = [serialize_student(student) for student in item.students.all()]
    return result


@api_errors
@transaction.atomic
def classes_collection(request):
    if request.method == "GET":
        items = SchoolClass.objects.annotate(student_count=Count("students")).order_by("name", "subject")
        return JsonResponse([serialize_class(item) for item in items], safe=False)
    if request.method == "POST":
        item = SchoolClass.objects.create(**class_fields(body(request)))
        return JsonResponse(serialize_class(item, True), status=201)
    return fail("Метод не поддерживается", 405)


@api_errors
@transaction.atomic
def class_detail(request, class_id):
    item = find(SchoolClass, class_id, "Класс")
    if request.method == "GET":
        return JsonResponse(serialize_class(item, True))
    if request.method == "PUT":
        for key, value in class_fields(body(request)).items():
            setattr(item, key, value)
        item.save()
        return JsonResponse(serialize_class(item, True))
    if request.method == "DELETE":
        item.delete()
        return JsonResponse({"ok": True})
    return fail("Метод не поддерживается", 405)


@api_errors
def class_students(request, class_id):
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    school_class = find(SchoolClass, class_id, "Класс")
    student = SchoolStudent.objects.create(school_class=school_class, **student_fields(body(request)))
    return JsonResponse(serialize_student(student), status=201)


@api_errors
def student_detail(request, student_id):
    student = find(SchoolStudent, student_id, "Ученик")
    if request.method == "PUT":
        for key, value in student_fields(body(request)).items():
            setattr(student, key, value)
        student.save()
        return JsonResponse(serialize_student(student))
    if request.method == "DELETE":
        student.delete()
        return JsonResponse({"ok": True})
    return fail("Метод не поддерживается", 405)


def lesson_fields(data):
    school_class = class_from(data)
    day = parse_date(data.get("date"))
    start = parse_time(data.get("time"))
    duration = number(data.get("duration_min"), "Длительность", 15, 240)
    if start.hour * 60 + start.minute + duration > 24 * 60:
        raise ValueError("Урок должен закончиться до полуночи")
    status = data.get("status", "planned")
    if status not in STATUSES:
        raise ValueError("Выберите статус урока")
    return {
        "school_class": school_class, "date": day, "time": start,
        "duration_min": duration, "topic": text(data.get("topic", ""), "Тема", 160),
        "comment": text(data.get("comment", ""), "Комментарий", 5000), "status": status,
    }


def serialize_lesson(item):
    rule = item.weekly_rule
    return {
        "id": str(item.id), "class_id": str(item.school_class_id),
        "class_name": item.school_class.name, "subject": item.school_class.subject,
        "date": item.date.isoformat(), "time": item.time.strftime("%H:%M"),
        "duration_min": item.duration_min, "topic": item.topic,
        "comment": item.comment, "status": item.status,
        "recurring": bool(rule), "weekly_rule_id": str(item.weekly_rule_id) if rule else None,
        "source_date": item.source_date.isoformat() if item.source_date else None,
        "rule": {
            "class_id": str(rule.school_class_id), "weekday": rule.weekday,
            "time": rule.time.strftime("%H:%M"), "duration_min": rule.duration_min,
            "topic": rule.topic,
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
    lessons = SchoolLesson.objects.filter(date__range=(start, end)).select_related("school_class", "weekly_rule")
    classes = SchoolClass.objects.order_by("name", "subject")
    return JsonResponse({
        "start": start.isoformat(), "end": end.isoformat(),
        "lessons": [serialize_lesson(item) for item in lessons],
        "classes": [{"id": str(item.id), "name": item.name, "subject": item.subject, "level": item.level} for item in classes],
    })


@api_errors
@transaction.atomic
def lessons_collection(request):
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    data = body(request)
    fields = lesson_fields(data)
    if fields["status"] != "planned":
        raise ValueError("Новый урок создаётся запланированным")
    repeat = data.get("repeat_weekly", False)
    if not isinstance(repeat, bool):
        raise ValueError("Некорректный параметр повтора")
    check_collision(fields["date"], fields["time"], fields["duration_min"])
    if repeat:
        weekday = fields["date"].weekday()
        check_rule_collision(weekday, fields["time"], fields["duration_min"], fields["date"])
        check_one_off_future_collisions(weekday, fields["time"], fields["duration_min"], fields["date"])
        rule = SchoolWeeklyRule.objects.create(
            school_class=fields["school_class"], weekday=weekday,
            time=fields["time"], duration_min=fields["duration_min"],
            topic=fields["topic"], start_date=fields["date"],
        )
        lesson = SchoolLesson.objects.create(**fields, weekly_rule=rule, source_date=fields["date"])
    else:
        lesson = SchoolLesson.objects.create(**fields)
    return JsonResponse(serialize_lesson(lesson), status=201)


@api_errors
@transaction.atomic
def lesson_detail(request, lesson_id):
    lesson = find(SchoolLesson, lesson_id, "Урок")
    if request.method == "PATCH":
        status = body(request).get("status")
        if status not in STATUSES:
            raise ValueError("Выберите статус урока")
        if status != "cancelled" and lesson.status == "cancelled":
            check_collision(lesson.date, lesson.time, lesson.duration_min, lesson.id)
        lesson.status = status
        if lesson.weekly_rule_id:
            lesson.is_override = True
        lesson.save()
        return JsonResponse(serialize_lesson(lesson))
    if request.method == "PUT":
        fields = lesson_fields(body(request))
        if fields["status"] != "cancelled":
            check_collision(fields["date"], fields["time"], fields["duration_min"], lesson.id)
        for key, value in fields.items():
            setattr(lesson, key, value)
        if lesson.weekly_rule_id:
            lesson.is_override = True
        lesson.save()
        return JsonResponse(serialize_lesson(lesson))
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
def rule_detail(request, rule_id):
    rule = find(SchoolWeeklyRule, rule_id, "Серия")
    data = body(request)
    from_date = parse_date(data.get("from_date"), "Дата изменения")
    if request.method == "PUT":
        school_class = class_from(data)
        weekday = number(data.get("weekday"), "День недели", 0, 6)
        time_value = parse_time(data.get("time"))
        duration = number(data.get("duration_min"), "Длительность", 15, 240)
        if time_value.hour * 60 + time_value.minute + duration > 24 * 60:
            raise ValueError("Урок должен закончиться до полуночи")
        new_rule = change_series(
            rule, from_date, school_class=school_class, weekday=weekday,
            time_value=time_value, duration=duration,
            topic=text(data.get("topic", ""), "Тема", 160),
        )
        return JsonResponse({"ok": True, "rule_id": str(new_rule.id)})
    if request.method == "DELETE":
        end_series(rule, from_date)
        return JsonResponse({"ok": True})
    return fail("Метод не поддерживается", 405)


def serialize_worksheet(item):
    return {"id": str(item.id), "class_id": str(item.school_class_id),
            "class_name": item.school_class.name, "subject": item.school_class.subject,
            "kind": item.kind, "title": item.title,
            "due_date": item.due_date.isoformat() if item.due_date else None,
            "created_at": item.created_at.isoformat(), "item_count": item.items.count()}


@api_errors
def worksheets_collection(request):
    if request.method != "GET":
        return fail("Метод не поддерживается", 405)
    class_id = request.GET.get("class_id")
    items = SchoolWorksheet.objects.select_related("school_class").prefetch_related("items")
    if class_id:
        try:
            items = items.filter(school_class_id=class_id)
        except (ValidationError, ValueError):
            raise ValueError("Некорректный ID класса") from None
    return JsonResponse([serialize_worksheet(item) for item in items], safe=False)


@api_errors
def worksheet_detail(request, worksheet_id):
    if request.method != "DELETE":
        return fail("Метод не поддерживается", 405)
    item = find(SchoolWorksheet, worksheet_id, "Подборка")
    item.delete()
    return JsonResponse({"ok": True})


@api_errors
def worksheet_pdf(request, worksheet_id):
    if request.method != "GET":
        return fail("Метод не поддерживается", 405)
    from assignments.pdf_export import build_pdf

    item = find(SchoolWorksheet, worksheet_id, "Подборка")
    answers = request.GET.get("solutions") == "1"
    result = HttpResponse(build_pdf(item, include_answers=answers), content_type="application/pdf")
    suffix = "solutions" if answers else "student"
    result["Content-Disposition"] = f'attachment; filename="school-worksheet-{item.id}-{suffix}.pdf"'
    return result
