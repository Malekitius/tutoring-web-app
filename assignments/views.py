"""One local workspace for lesson tasks, homework and reusable exercises."""

import json
import uuid
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from schedule.models import Lesson
from students.models import Student
from students.views import api_errors, body, fail, number, text

from .models import Exercise, ExerciseGrade, Submission, Worksheet, WorksheetItem
from .pdf_export import build_pdf
from .pdf_export import format_text


LIBRARY_FORMAT = "tutoring-web-app.exercise-library"
LIBRARY_VERSION = 2
LEGACY_DIFFICULTY = {1: 1, 2: 2, 3: 2, 4: 3, 5: 3}
LIBRARY_KEYS = {"id", "title", "prompt", "answer", "subject", "grades", "topic", "subtopic", "difficulty"}


@ensure_csrf_cookie
def assignments_page(request):
    return render(request, "assignments.html")


def find(model, item_id, label):
    item = model.objects.filter(id=item_id).first()
    if item is None:
        raise LookupError(f"{label} не найдено")
    return item


def optional_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("Укажите корректный дедлайн") from None


def exercise_fields(data):
    subject = text(data.get("subject", ""), "Предмет", 80, True)
    raw_grades = data.get("grades", [data.get("grade")])
    if not isinstance(raw_grades, list) or not raw_grades or len(raw_grades) > 11:
        raise ValueError("Выберите от 1 до 11 классов")
    grades = [number(grade, "Класс", 1, 11) for grade in raw_grades]
    if len(grades) != len(set(grades)):
        raise ValueError("Классы не должны повторяться")
    fields = {
        "title": text(data.get("title", ""), "Название", 160, True),
        "prompt": text(data.get("prompt", ""), "Условие", 10000, True),
        "answer": text(data.get("answer", ""), "Решение", 10000),
        "subject": subject,
        "topic": text(data.get("topic", ""), "Тема", 160),
        "subtopic": text(data.get("subtopic", ""), "Подтема", 160),
        "difficulty": number(data.get("difficulty", 2), "Сложность", 1, 4),
        "grades": sorted(grades),
    }
    for key in ("prompt", "answer"):
        format_text(fields[key])
    return fields


def worksheet_fields(data):
    try:
        student = Student.objects.filter(id=data.get("student_id")).first()
    except (ValidationError, ValueError):
        student = None
    if student is None:
        raise ValueError("Выберите ученика")
    kind = data.get("kind")
    if kind not in {"lesson", "homework"}:
        raise ValueError("Выберите тип задания")
    lesson = None
    if data.get("lesson_id"):
        try:
            lesson = Lesson.objects.filter(id=data["lesson_id"], student=student).first()
        except (ValidationError, ValueError):
            lesson = None
        if lesson is None:
            raise ValueError("Выбранное занятие не относится к ученику")
    due = optional_date(data.get("due_date"))
    if kind == "lesson" and due:
        raise ValueError("Дедлайн задаётся только для домашней работы")
    return {
        "student": student, "lesson": lesson, "kind": kind,
        "title": text(data.get("title", ""), "Название", 160, True),
        "instructions": text(data.get("instructions", ""), "Инструкция", 5000),
        "due_date": due,
    }


def serialize_exercise(item):
    grades = [grade.grade for grade in item.grade_levels.all()]
    return {"id": str(item.id), "title": item.title, "prompt": item.prompt,
            "answer": item.answer, "subject": item.subject, "grades": grades,
            "topic": item.topic, "subtopic": item.subtopic,
            "difficulty": item.difficulty, "updated_at": item.updated_at.isoformat()}


def serialize_item(item):
    return {"id": str(item.id), "source_id": str(item.source_id) if item.source_id else None,
            "position": item.position, "title": item.title, "prompt": item.prompt,
            "answer": item.answer}


def serialize_submission(item):
    return {"id": str(item.id), "original_name": item.original_name,
            "note": item.note, "created_at": item.created_at.isoformat(),
            "url": f"/api/assignments/submissions/{item.id}/file"}


def serialize_worksheet(item, detailed=False):
    result = {
        "id": str(item.id), "student_id": str(item.student_id),
        "student_name": item.student.name, "grade": item.student.grade,
        "lesson_id": str(item.lesson_id) if item.lesson_id else None,
        "lesson_date": item.lesson.date.isoformat() if item.lesson_id else None,
        "kind": item.kind, "title": item.title, "instructions": item.instructions,
        "due_date": item.due_date.isoformat() if item.due_date else None,
        "status": item.status, "feedback": item.feedback,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }
    if detailed:
        result["items"] = [serialize_item(entry) for entry in item.items.all()]
        result["submissions"] = [serialize_submission(entry) for entry in item.submissions.all()]
    else:
        result["item_count"] = item.items.count()
        result["submission_count"] = item.submissions.count()
    return result


@api_errors
def overview(request):
    if request.method != "GET":
        return fail("Метод не поддерживается", 405)
    students = Student.objects.order_by("name")
    worksheets = Worksheet.objects.select_related("student", "lesson").prefetch_related("items", "submissions")
    lessons = Lesson.objects.select_related("student").order_by("-date", "-time")
    return JsonResponse({
        "students": [{"id": str(item.id), "name": item.name, "grade": item.grade} for item in students],
        "lessons": [{"id": str(item.id), "student_id": str(item.student_id),
                     "date": item.date.isoformat(), "time": item.time.strftime("%H:%M"),
                     "student_name": item.student.name} for item in lessons],
        "worksheets": [serialize_worksheet(item) for item in worksheets],
        "exercise_count": Exercise.objects.count(),
    })


@api_errors
def exercises_collection(request):
    if request.method == "GET":
        subjects = [value.strip() for value in request.GET.getlist("subject") if value.strip()]
        topics_filter = [value.strip() for value in request.GET.getlist("topic") if value.strip()]
        subtopics_filter = [value.strip() for value in request.GET.getlist("subtopic") if value.strip()]
        query = request.GET.get("q", "").strip()[:160]
        grades = [number(value, "Класс", 1, 11) for value in request.GET.getlist("grade") if value]
        difficulties = [number(value, "Сложность", 1, 4) for value in request.GET.getlist("difficulty") if value]
        if any(len(values) > 100 for values in (subjects, topics_filter, subtopics_filter, grades, difficulties)):
            raise ValueError("Слишком много значений фильтра")
        page = number(request.GET.get("page", 1), "Страница", 1, 1_000_000)
        page_size = number(request.GET.get("page_size", 40), "Размер страницы", 1, 100)
        base = Exercise.objects.all()
        if subjects:
            base = base.filter(subject__in=subjects)
        topics = list(base.exclude(topic="").order_by("topic").values_list("topic", flat=True).distinct())
        if topics_filter:
            base = base.filter(topic__in=topics_filter)
        subtopics = list(base.exclude(subtopic="").order_by("subtopic").values_list("subtopic", flat=True).distinct())
        items = base
        if subtopics_filter:
            items = items.filter(subtopic__in=subtopics_filter)
        if grades:
            items = items.filter(grade_levels__grade__in=grades).distinct()
        if difficulties:
            items = items.filter(difficulty__in=difficulties)
        if query:
            items = items.filter(Q(title__icontains=query) | Q(topic__icontains=query) |
                                 Q(subtopic__icontains=query) | Q(prompt__icontains=query))
        total = items.count()
        items = items.order_by("subject", "topic", "subtopic", "title", "id")
        start = (page - 1) * page_size
        return JsonResponse({
            "items": [serialize_exercise(item) for item in items.prefetch_related("grade_levels")[start:start + page_size]],
            "total": total, "page": page, "page_size": page_size,
            "facets": {"subjects": list(Exercise.objects.order_by("subject").values_list("subject", flat=True).distinct()), "topics": topics,
                       "subtopics": subtopics},
        })
    if request.method == "POST":
        fields = exercise_fields(body(request))
        grades = fields.pop("grades")
        with transaction.atomic():
            item = Exercise.objects.create(**fields)
            ExerciseGrade.objects.bulk_create(ExerciseGrade(exercise=item, grade=grade) for grade in grades)
        return JsonResponse(serialize_exercise(item), status=201)
    return fail("Метод не поддерживается", 405)


@api_errors
def library_export(request):
    if request.method != "GET":
        return fail("Метод не поддерживается", 405)
    exercises = Exercise.objects.prefetch_related("grade_levels").order_by("id")
    rows = []
    for item in exercises:
        serialized = serialize_exercise(item)
        rows.append({key: serialized[key] for key in (
            "id", "title", "prompt", "answer", "subject", "grades", "topic", "subtopic", "difficulty"
        )})
    payload = {"format": LIBRARY_FORMAT, "version": LIBRARY_VERSION, "exercises": rows}
    result = HttpResponse(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", content_type="application/json; charset=utf-8")
    result["Content-Disposition"] = 'attachment; filename="exercise-library-v2.json"'
    return result


def parse_library_upload(file):
    if not file or file.size > 20 * 1024 * 1024:
        raise ValueError("Выберите файл JSON размером до 20 МБ")
    try:
        document = json.loads(file.read().decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Файл должен содержать корректный JSON в UTF-8") from None
    if not isinstance(document, dict) or set(document) != {"format", "version", "exercises"}:
        raise ValueError("Неверная структура библиотеки")
    if document["format"] != LIBRARY_FORMAT or type(document["version"]) is not int or document["version"] not in (1, 2):
        raise ValueError("Неподдерживаемая версия библиотеки")
    rows = document["exercises"]
    if not isinstance(rows, list) or len(rows) > 10_000:
        raise ValueError("Библиотека должна содержать не более 10 000 задач")
    normalized = []
    ids = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or set(row) != LIBRARY_KEYS:
            raise ValueError(f"Задача {index}: неверный набор полей")
        try:
            item_id = str(uuid.UUID(row["id"])) if isinstance(row["id"], str) else None
        except ValueError:
            item_id = None
        if not item_id:
            raise ValueError(f"Задача {index}: неверный ID")
        if item_id in ids:
            raise ValueError(f"Задача {index}: повторяющийся ID")
        ids.add(item_id)
        if not isinstance(row["grades"], list) or any(type(grade) is not int for grade in row["grades"]):
            raise ValueError(f"Задача {index}: классы должны быть целыми числами")
        if type(row["difficulty"]) is not int:
            raise ValueError(f"Задача {index}: сложность должна быть целым числом")
        if document["version"] == 1:
            if row["difficulty"] not in LEGACY_DIFFICULTY:
                raise ValueError(f"Задача {index}: неверная сложность")
            row = {**row, "difficulty": LEGACY_DIFFICULTY[row["difficulty"]]}
        fields = exercise_fields(row)
        normalized.append((item_id, fields))
    return normalized


@api_errors
@transaction.atomic
def library_import(request):
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    entries = parse_library_upload(request.FILES.get("file"))
    existing = {str(item.id): item for item in Exercise.objects.filter(
        id__in=[item_id for item_id, _ in entries]
    ).prefetch_related("grade_levels")}
    created = updated = unchanged = 0
    dry_run = request.GET.get("dry_run") == "1"
    for item_id, fields in entries:
        grades = fields["grades"]
        values = {key: value for key, value in fields.items() if key != "grades"}
        item = existing.get(item_id)
        if item is None:
            created += 1
            if not dry_run:
                item = Exercise.objects.create(id=uuid.UUID(item_id), **values)
                ExerciseGrade.objects.bulk_create(ExerciseGrade(exercise=item, grade=grade) for grade in grades)
            continue
        same = all(getattr(item, key) == value for key, value in values.items()) and [g.grade for g in item.grade_levels.all()] == grades
        if same:
            unchanged += 1
            continue
        updated += 1
        if not dry_run:
            for key, value in values.items():
                setattr(item, key, value)
            item.save()
            item.grade_levels.all().delete()
            ExerciseGrade.objects.bulk_create(ExerciseGrade(exercise=item, grade=grade) for grade in grades)
    return JsonResponse({"created": created, "updated": updated, "unchanged": unchanged,
                         "total": len(entries), "dry_run": dry_run})


@api_errors
def exercise_detail(request, exercise_id):
    item = find(Exercise, exercise_id, "Задание")
    if request.method == "PUT":
        fields = exercise_fields(body(request))
        grades = fields.pop("grades")
        with transaction.atomic():
            for key, value in fields.items():
                setattr(item, key, value)
            item.save()
            item.grade_levels.all().delete()
            ExerciseGrade.objects.bulk_create(ExerciseGrade(exercise=item, grade=grade) for grade in grades)
        return JsonResponse(serialize_exercise(item))
    if request.method == "DELETE":
        item.delete()
        return JsonResponse({"ok": True})
    return fail("Метод не поддерживается", 405)


@api_errors
def worksheets_collection(request):
    if request.method == "GET":
        items = Worksheet.objects.select_related("student", "lesson")
        return JsonResponse([serialize_worksheet(item) for item in items], safe=False)
    if request.method == "POST":
        item = Worksheet.objects.create(**worksheet_fields(body(request)))
        return JsonResponse(serialize_worksheet(item, True), status=201)
    return fail("Метод не поддерживается", 405)


@api_errors
@transaction.atomic
def worksheet_detail(request, worksheet_id):
    item = find(Worksheet, worksheet_id, "Подборка")
    if request.method == "GET":
        return JsonResponse(serialize_worksheet(item, True))
    if request.method == "PUT":
        data = body(request)
        fields = worksheet_fields(data)
        if item.submissions.exists() and fields["student"] != item.student:
            raise ValueError("У работы уже есть решения; ученика менять нельзя")
        for key, value in fields.items():
            setattr(item, key, value)
        item.save()
        return JsonResponse(serialize_worksheet(item, True))
    if request.method == "PATCH":
        data = body(request)
        status = data.get("status")
        if status not in dict(Worksheet.STATUS_CHOICES):
            raise ValueError("Некорректный статус")
        if item.kind == "lesson" and status in {"submitted", "reviewed", "revision"}:
            raise ValueError("Проверка доступна только для домашней работы")
        item.status = status
        if "feedback" in data:
            item.feedback = text(data["feedback"], "Комментарий к проверке", 5000)
        item.save(update_fields=["status", "feedback", "updated_at"])
        return JsonResponse(serialize_worksheet(item, True))
    if request.method == "DELETE":
        item.delete()
        return JsonResponse({"ok": True})
    return fail("Метод не поддерживается", 405)


@api_errors
def worksheet_pdf(request, worksheet_id):
    if request.method != "GET":
        return fail("Метод не поддерживается", 405)
    item = find(Worksheet, worksheet_id, "Подборка")
    include_answers = request.GET.get("solutions") == "1"
    pdf = build_pdf(item, include_answers=include_answers)
    response = HttpResponse(pdf, content_type="application/pdf")
    suffix = "solutions" if include_answers else "student"
    response["Content-Disposition"] = f'attachment; filename="worksheet-{item.id}-{suffix}.pdf"'
    return response


@api_errors
def worksheet_items(request, worksheet_id):
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    worksheet = find(Worksheet, worksheet_id, "Подборка")
    data = body(request)
    source = None
    if data.get("source_id"):
        try:
            source = Exercise.objects.filter(id=data["source_id"]).first()
        except (ValidationError, ValueError):
            source = None
        if source is None:
            raise ValueError("Задача из библиотеки не найдена")
        fields = {"title": source.title, "prompt": source.prompt, "answer": source.answer}
    else:
        fields = {"title": text(data.get("title", ""), "Название", 160, True),
                  "prompt": text(data.get("prompt", ""), "Условие", 10000, True),
                  "answer": text(data.get("answer", ""), "Решение", 10000)}
    position = max((item.position for item in worksheet.items.all()), default=0) + 1
    item = WorksheetItem.objects.create(worksheet=worksheet, source=source, position=position, **fields)
    return JsonResponse(serialize_item(item), status=201)


@api_errors
@transaction.atomic
def worksheet_items_batch(request, worksheet_id):
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    worksheet = find(Worksheet, worksheet_id, "Подборка")
    exercise_ids = body(request).get("exercise_ids")
    if not isinstance(exercise_ids, list) or not 1 <= len(exercise_ids) <= 100:
        raise ValueError("Выберите от 1 до 100 задач")
    try:
        ids = [uuid.UUID(value) for value in exercise_ids if isinstance(value, str)]
    except (ValueError, AttributeError):
        ids = []
    if len(ids) != len(exercise_ids) or len(set(ids)) != len(ids):
        raise ValueError("Список задач содержит неверные или повторяющиеся ID")
    sources = Exercise.objects.in_bulk(ids)
    if len(sources) != len(ids):
        raise ValueError("Одна из задач библиотеки не найдена")
    if worksheet.items.filter(source_id__in=ids).exists():
        raise ValueError("Одна из задач уже есть в подборке")
    position = max((item.position for item in worksheet.items.all()), default=0)
    if position + len(ids) > 65535:
        raise ValueError("Слишком много задач в подборке")
    items = []
    for source_id in ids:
        source = sources[source_id]
        position += 1
        items.append(WorksheetItem.objects.create(
            worksheet=worksheet, source=source, position=position,
            title=source.title, prompt=source.prompt, answer=source.answer,
        ))
    return JsonResponse({"items": [serialize_item(item) for item in items]}, status=201)


@api_errors
def item_detail(request, item_id):
    item = find(WorksheetItem, item_id, "Задача")
    if request.method == "PUT":
        data = body(request)
        item.title = text(data.get("title", ""), "Название", 160, True)
        item.prompt = text(data.get("prompt", ""), "Условие", 10000, True)
        item.answer = text(data.get("answer", ""), "Решение", 10000)
        item.save(update_fields=["title", "prompt", "answer"])
        return JsonResponse(serialize_item(item))
    if request.method == "DELETE":
        item.delete()
        return JsonResponse({"ok": True})
    return fail("Метод не поддерживается", 405)


def valid_upload(file):
    if not file or file.size > 20 * 1024 * 1024:
        raise ValueError("Выберите файл размером до 20 МБ")
    name = file.name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    signature = file.read(16)
    file.seek(0)
    supported = {
        "pdf": signature.startswith(b"%PDF-"),
        "png": signature.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": signature.startswith(b"\xff\xd8\xff"),
        "jpeg": signature.startswith(b"\xff\xd8\xff"),
        "webp": signature.startswith(b"RIFF") and signature[8:12] == b"WEBP",
    }
    if not supported.get(extension):
        raise ValueError("Можно загрузить PDF, PNG, JPG или WebP")
    return name[:255]


@api_errors
def submissions_collection(request, worksheet_id):
    if request.method != "POST":
        return fail("Метод не поддерживается", 405)
    worksheet = find(Worksheet, worksheet_id, "Домашняя работа")
    if worksheet.kind != "homework":
        raise ValueError("Решения можно загрузить только для домашней работы")
    file = request.FILES.get("file")
    filename = valid_upload(file)
    note = text(request.POST.get("note", ""), "Комментарий", 1000)
    submission = Submission.objects.create(worksheet=worksheet, file=file, original_name=filename, note=note)
    worksheet.status = "submitted"
    worksheet.save(update_fields=["status", "updated_at"])
    return JsonResponse(serialize_submission(submission), status=201)


@api_errors
def submission_file(request, submission_id):
    if request.method != "GET":
        return fail("Метод не поддерживается", 405)
    item = find(Submission, submission_id, "Файл")
    return FileResponse(item.file.open("rb"), as_attachment=True, filename=item.original_name)


@api_errors
def submission_detail(request, submission_id):
    if request.method != "DELETE":
        return fail("Метод не поддерживается", 405)
    item = find(Submission, submission_id, "Файл")
    worksheet = item.worksheet
    item.delete()
    if worksheet.status == "submitted" and not worksheet.submissions.exists():
        worksheet.status = "assigned"
        worksheet.save(update_fields=["status", "updated_at"])
    return JsonResponse({"ok": True})


@receiver(pre_delete, sender=Submission)
def remove_submission_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)
