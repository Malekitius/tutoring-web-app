"""Explicitly selected teaching context. Money fields and finance models are excluded."""

from django.utils import timezone

from assignments.models import Worksheet
from schedule.models import Lesson, LessonComment
from students.models import Student
from .policy import teaching_text


def student_context(student: Student) -> dict:
    subjects = student.subjects.prefetch_related("topics").all()
    lessons = Lesson.objects.filter(student=student).select_related("subject").order_by("-date", "-time")[:24]
    notes = LessonComment.objects.filter(student=student).select_related("lesson").order_by("-created_at")[:24]
    worksheets = Worksheet.objects.filter(student=student).order_by("-created_at")[:12]
    return {
        "сегодня": timezone.localdate().isoformat(),
        "класс": student.grade,
        "общая_цель": teaching_text(student.goal),
        "предметы": [
            {"название": subject.name, "уровень": subject.level, "цель": teaching_text(subject.goal),
             "темы": [{"название": teaching_text(topic.title), "освоение_от_0_до_3": topic.mastery,
                        "комментарий": teaching_text(topic.notes)} for topic in subject.topics.all()]}
            for subject in subjects
        ],
        "последние_занятия": [
            {"дата": lesson.date.isoformat(), "время": lesson.time.strftime("%H:%M"),
             "предмет": lesson.subject.name if lesson.subject else "не указан",
             "статус": lesson.status} for lesson in lessons
        ],
        "заметки": [
            {"текст": teaching_text(note.body), "приоритет": note.priority,
             "дата_занятия": note.lesson.date.isoformat() if note.lesson else None,
             "дедлайн": note.due_date.isoformat() if note.due_date else None}
            for note in notes
        ],
        "последние_подборки": [
            {"название": teaching_text(worksheet.title), "тип": worksheet.kind,
             "статус": worksheet.status, "инструкция": teaching_text(worksheet.instructions),
             "отзыв": teaching_text(worksheet.feedback)} for worksheet in worksheets
        ],
    }
