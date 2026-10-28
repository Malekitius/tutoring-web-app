"""Shared validation and presentation of notes from lessons and student cards."""

from datetime import date

from .models import LessonComment


PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3}


def note_fields(data):
    body = data.get("body", "")
    if not isinstance(body, str):
        raise ValueError("Комментарий должен быть текстом")
    body = body.strip()
    if not body:
        raise ValueError("Заполните поле «Комментарий»")
    if len(body) > 5000:
        raise ValueError("Комментарий слишком длинный (до 5000 символов)")

    priority = data.get("priority", "none")
    if not isinstance(priority, str) or priority not in {"none", "low", "medium", "high"}:
        raise ValueError("Выберите приоритет комментария")

    due_date = data.get("due_date")
    if due_date:
        try:
            due_date = date.fromisoformat(due_date)
        except (TypeError, ValueError):
            raise ValueError("Поле «Дедлайн» содержит некорректную дату") from None
    else:
        due_date = None

    return {"body": body, "priority": priority, "due_date": due_date}


def serialize_note(comment, lesson=None):
    linked_lesson = lesson if lesson is not None else comment.lesson
    return {
        "id": str(comment.id), "student_id": str(comment.student_id),
        "lesson_id": str(comment.lesson_id) if comment.lesson_id else None,
        "lesson_date": linked_lesson.date.isoformat() if linked_lesson else None,
        "lesson_time": linked_lesson.time.strftime("%H:%M") if linked_lesson else None,
        "body": comment.body, "priority": comment.priority,
        "due_date": comment.due_date.isoformat() if comment.due_date else None,
        "created_at": comment.created_at.isoformat(),
        "updated_at": comment.updated_at.isoformat(),
    }


def sort_notes(notes):
    return sorted(notes, key=lambda note: (
        PRIORITY_ORDER.get(note.priority, 3),
        note.due_date is None,
        note.due_date or date.max,
        -note.created_at.timestamp(),
        str(note.id),
    ))


def notes_for_student(student):
    return sort_notes(LessonComment.objects.filter(student=student).select_related("lesson"))
