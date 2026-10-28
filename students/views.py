"""Page and small JSON API for local student cards."""

import json
from functools import wraps

from django.db import IntegrityError
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from schedule.models import LessonComment
from schedule.notes import note_fields, notes_for_student, serialize_note

from .icons import SUBJECT_ICON_IDS, SUBJECT_ICONS, default_icon_for_name
from .models import Student, Subject, Topic


MAX_BODY = 1_000_000
LEVELS = {choice[0] for choice in Subject.LEVEL_CHOICES}


@ensure_csrf_cookie
def index(request):
    return render(request, "index.html", {"subject_icons": SUBJECT_ICONS})


def fail(message, status=400):
    return JsonResponse({"error": message}, status=status)


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
            return fail("Этот предмет уже есть в карточке ученика", 409)

    return wrapped


def body(request):
    if not 0 < len(request.body) <= MAX_BODY:
        raise ValueError("Размер запроса недопустим")
    try:
        result = json.loads(request.body)
    except json.JSONDecodeError:
        raise ValueError("Некорректный JSON") from None
    if not isinstance(result, dict):
        raise ValueError("Ожидался объект JSON")
    return result


def text(value, label, limit, required=False):
    if not isinstance(value, str):
        raise ValueError(f"Поле «{label}» должно быть текстом")
    value = value.strip()
    if required and not value:
        raise ValueError(f"Заполните поле «{label}»")
    if len(value) > limit:
        raise ValueError(f"Поле «{label}» слишком длинное (до {limit} символов)")
    return value


def number(value, label, minimum, maximum):
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"Некорректное значение поля «{label}»")
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"Некорректное значение поля «{label}»") from None
    if not minimum <= result <= maximum:
        raise ValueError(f"Поле «{label}» должно быть от {minimum} до {maximum}")
    return result


def student_fields(data):
    result = {
        "name": text(data.get("name", ""), "Имя ученика", 120, True),
        "grade": number(data.get("grade"), "Класс", 1, 11),
        "status": data.get("status", "active"),
        "goal": text(data.get("goal", ""), "Общая цель", 1000),
        "price_rub": number(data.get("price_rub", 0), "Стоимость занятия", 0, 1_000_000),
        "duration_min": number(data.get("duration_min", 60), "Длительность", 15, 240),
    }
    if result["status"] not in {"active", "paused"}:
        raise ValueError("Некорректный статус ученика")
    return result


def subject_fields(data, existing=None):
    name = text(data.get("name", ""), "Предмет", 80, True)
    icon = data.get("icon", existing.icon if existing else default_icon_for_name(name))
    if not isinstance(icon, str) or (icon not in SUBJECT_ICON_IDS and icon != ""):
        raise ValueError("Выберите иконку из списка")
    result = {
        "name": name,
        "icon": icon,
        "level": data.get("level", "базовый"),
        "goal": text(data.get("goal", ""), "Цель по предмету", 1000),
    }
    if result["level"] not in LEVELS:
        raise ValueError("Выберите уровень")
    return result


def topic_fields(data):
    return {
        "title": text(data.get("title", ""), "Тема", 160, True),
        "mastery": number(data.get("mastery", 0), "Освоение", 0, 3),
        "notes": text(data.get("notes", ""), "Комментарий", 1000),
    }


def find(model, **kwargs):
    item = model.objects.filter(**kwargs).first()
    if item is None:
        raise LookupError({Student: "Ученик", Subject: "Предмет", Topic: "Тема"}[model] + " не найден(а)")
    return item


def serialize_topic(topic):
    return {
        "id": str(topic.id),
        "subject_id": str(topic.subject_id),
        "title": topic.title,
        "mastery": topic.mastery,
        "notes": topic.notes,
        "updated_at": topic.updated_at.isoformat(),
    }


def serialize_subject(subject):
    return {
        "id": str(subject.id),
        "student_id": str(subject.student_id),
        "name": subject.name,
        "icon": subject.icon,
        "level": subject.level,
        "goal": subject.goal,
        "topics": [serialize_topic(topic) for topic in subject.topics.all()],
    }


def serialize_student(student):
    return {
        "id": str(student.id),
        "name": student.name,
        "grade": student.grade,
        "status": student.status,
        "goal": student.goal,
        "notes": [serialize_note(note) for note in notes_for_student(student)],
        "price_rub": student.price_rub,
        "duration_min": student.duration_min,
        "created_at": student.created_at.isoformat(),
        "updated_at": student.updated_at.isoformat(),
        "subjects": [serialize_subject(subject) for subject in student.subjects.all()],
    }


def list_student(student):
    return {
        "id": str(student.id),
        "name": student.name,
        "grade": student.grade,
        "status": student.status,
        "subject_count": student.subject_count,
    }


@api_errors
def students_collection(request):
    if request.method == "GET":
        students = Student.objects.annotate(subject_count=Count("subjects")).order_by("status", "name")
        return JsonResponse([list_student(item) for item in students], safe=False)
    if request.method == "POST":
        student = Student.objects.create(**student_fields(body(request)))
        return JsonResponse(serialize_student(student), status=201)
    return fail("Метод не поддерживается", 405)


@api_errors
def student_detail(request, student_id):
    student = find(Student, id=student_id)
    if request.method == "GET":
        return JsonResponse(serialize_student(student))
    if request.method == "PUT":
        for key, value in student_fields(body(request)).items():
            setattr(student, key, value)
        student.save()
        return JsonResponse(serialize_student(student))
    if request.method == "DELETE":
        if student.payments.exists() or student.lessons.filter(status="completed").exists():
            return fail(
                "У ученика есть внесения или проведённые занятия. Для сохранения финансовой истории переведите его в статус «На паузе».",
                409,
            )
        student.delete()
        return JsonResponse({"ok": True})
    return fail("Метод не поддерживается", 405)


@api_errors
def student_notes(request, student_id):
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    student = find(Student, id=student_id)
    note = LessonComment.objects.create(student=student, **note_fields(body(request)))
    return JsonResponse(serialize_note(note), status=201)


@api_errors
def note_detail(request, note_id):
    note = LessonComment.objects.filter(id=note_id).select_related("lesson").first()
    if note is None:
        raise LookupError("Заметка не найдена")
    if request.method == "PUT":
        for key, value in note_fields(body(request)).items():
            setattr(note, key, value)
        note.save()
        return JsonResponse(serialize_note(note))
    if request.method == "DELETE":
        note.delete()
        return JsonResponse({"ok": True})
    return fail("Метод не поддерживается", 405)


@api_errors
def student_subjects(request, student_id):
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    student = find(Student, id=student_id)
    subject = Subject.objects.create(student=student, **subject_fields(body(request)))
    return JsonResponse(serialize_subject(subject), status=201)


@api_errors
def subject_detail(request, subject_id):
    subject = find(Subject, id=subject_id)
    if request.method == "PUT":
        for key, value in subject_fields(body(request), subject).items():
            setattr(subject, key, value)
        subject.save()
        return JsonResponse(serialize_subject(subject))
    if request.method == "DELETE":
        subject.delete()
        return JsonResponse({"ok": True})
    return fail("Метод не поддерживается", 405)


@api_errors
def subject_topics(request, subject_id):
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    subject = find(Subject, id=subject_id)
    topic = Topic.objects.create(subject=subject, **topic_fields(body(request)))
    return JsonResponse(serialize_topic(topic), status=201)


@api_errors
def topic_detail(request, topic_id):
    topic = find(Topic, id=topic_id)
    if request.method == "PUT":
        for key, value in topic_fields(body(request)).items():
            setattr(topic, key, value)
        topic.save()
        return JsonResponse(serialize_topic(topic))
    if request.method == "DELETE":
        topic.delete()
        return JsonResponse({"ok": True})
    return fail("Метод не поддерживается", 405)
