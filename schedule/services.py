"""Calendar rules and collision checks, shared by API and future finance views."""

from datetime import date, timedelta

from django.db import transaction
from django.db.models import Q

from .models import Lesson, WeeklyRule


def minutes(time_value):
    return time_value.hour * 60 + time_value.minute


def overlaps(first_time, first_duration, second_time, second_duration):
    first_start = minutes(first_time)
    second_start = minutes(second_time)
    return first_start < second_start + second_duration and second_start < first_start + first_duration


def ensure_occurrences(start: date, end: date):
    """Materialize weekly lessons only for the requested range."""
    rules = WeeklyRule.objects.filter(start_date__lte=end).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=start)
    ).select_related("student", "subject")
    new_lessons = []
    for rule in rules:
        cursor = max(start, rule.start_date)
        cursor += timedelta(days=(rule.weekday - cursor.weekday()) % 7)
        last = min(end, rule.end_date) if rule.end_date else end
        while cursor <= last:
            new_lessons.append(Lesson(
                student=rule.student, subject=rule.subject, date=cursor,
                time=rule.time, duration_min=rule.duration_min,
                weekly_rule=rule, source_date=cursor,
            ))
            cursor += timedelta(days=7)
    Lesson.objects.bulk_create(new_lessons, ignore_conflicts=True)


def check_collision(day, time_value, duration, exclude_id=None):
    ensure_occurrences(day, day)
    lessons = Lesson.objects.filter(date=day).exclude(status="cancelled")
    if exclude_id:
        lessons = lessons.exclude(id=exclude_id)
    for existing in lessons.select_related("student"):
        if overlaps(time_value, duration, existing.time, existing.duration_min):
            raise ValueError(
                f"В это время уже есть занятие: {existing.student.name}, "
                f"{existing.time.strftime('%H:%M')}"
            )
    from school.models import SchoolLesson
    from school.services import ensure_occurrences as ensure_school_occurrences

    ensure_school_occurrences(day, day)
    for existing in SchoolLesson.objects.filter(date=day).exclude(status="cancelled").select_related("school_class"):
        if overlaps(time_value, duration, existing.time, existing.duration_min):
            raise ValueError(f"В это время уже есть урок класса {existing.school_class.name}, {existing.time:%H:%M}")


def check_rule_collision(weekday, time_value, duration, start_date, end_date=None, exclude_rule_id=None):
    rules = WeeklyRule.objects.filter(weekday=weekday, start_date__lte=end_date or date.max)
    for rule in rules:
        if exclude_rule_id and rule.id == exclude_rule_id:
            continue
        if rule.end_date and rule.end_date < rule.start_date:
            # Legacy empty series created by ending it at its first lesson.
            continue
        if rule.end_date and rule.end_date < start_date:
            continue
        if overlaps(time_value, duration, rule.time, rule.duration_min):
            raise ValueError(
                "Еженедельное занятие пересекается с другой серией: "
                f"{rule.student.name}, {rule.time.strftime('%H:%M')}"
            )
    from school.models import SchoolWeeklyRule

    school_rules = SchoolWeeklyRule.objects.filter(weekday=weekday, start_date__lte=end_date or date.max)
    for rule in school_rules.select_related("school_class"):
        if rule.end_date and rule.end_date < start_date:
            continue
        if overlaps(time_value, duration, rule.time, rule.duration_min):
            raise ValueError(f"Серия пересекается с уроком класса {rule.school_class.name} в {rule.time:%H:%M}")


def check_one_off_future_collisions(weekday, time_value, duration, start_date, end_date=None, exclude_rule_id=None):
    """Check existing one-off and manually moved lessons against a new rule."""
    lessons = Lesson.objects.filter(date__gte=start_date).exclude(status="cancelled")
    if end_date:
        lessons = lessons.filter(date__lte=end_date)
    for lesson in lessons.select_related("student"):
        if lesson.date.weekday() != weekday:
            continue
        if lesson.weekly_rule_id and not lesson.is_override:
            # Such lessons are covered by check_rule_collision.
            continue
        if overlaps(time_value, duration, lesson.time, lesson.duration_min):
            raise ValueError(
                f"Серия пересекается с занятием {lesson.student.name} "
                f"{lesson.date.strftime('%d.%m')} в {lesson.time.strftime('%H:%M')}"
            )
    from school.models import SchoolLesson

    school_lessons = SchoolLesson.objects.filter(date__gte=start_date).exclude(status="cancelled")
    if end_date:
        school_lessons = school_lessons.filter(date__lte=end_date)
    for lesson in school_lessons.select_related("school_class"):
        if lesson.date.weekday() != weekday or (lesson.weekly_rule_id and not lesson.is_override):
            continue
        if overlaps(time_value, duration, lesson.time, lesson.duration_min):
            raise ValueError(
                f"Серия пересекается с уроком класса {lesson.school_class.name} "
                f"{lesson.date:%d.%m} в {lesson.time:%H:%M}"
            )


@transaction.atomic
def change_series(rule, from_date, *, student, subject, weekday, time_value, duration):
    if from_date < rule.start_date or (rule.end_date and from_date > rule.end_date):
        raise ValueError("Дата изменения не входит в эту серию")
    new_start = from_date + timedelta(days=(weekday - from_date.weekday()) % 7)
    if rule.end_date and new_start > rule.end_date:
        raise ValueError("Новый день недели выходит за пределы серии")
    check_rule_collision(weekday, time_value, duration, new_start, rule.end_date, rule.id)
    check_one_off_future_collisions(weekday, time_value, duration, new_start, rule.end_date, rule.id)

    Lesson.objects.filter(weekly_rule=rule, source_date__gte=from_date, is_override=False).delete()
    # Manually changed lessons remain independent when the future series is split.
    Lesson.objects.filter(weekly_rule=rule, source_date__gte=from_date, is_override=True).update(
        weekly_rule=None, source_date=None
    )
    if from_date == rule.start_date:
        rule.student = student
        rule.subject = subject
        rule.weekday = weekday
        rule.time = time_value
        rule.duration_min = duration
        rule.start_date = new_start
        rule.save()
        return rule

    old_end = rule.end_date
    rule.end_date = from_date - timedelta(days=1)
    rule.save(update_fields=["end_date"])
    return WeeklyRule.objects.create(
        student=student, subject=subject, weekday=weekday,
        time=time_value, duration_min=duration,
        start_date=new_start, end_date=old_end,
    )


@transaction.atomic
def end_series(rule, from_date):
    if from_date < rule.start_date or (rule.end_date and from_date > rule.end_date):
        raise ValueError("Дата завершения не входит в эту серию")
    Lesson.objects.filter(weekly_rule=rule, source_date__gte=from_date).exclude(status="completed").delete()
    Lesson.objects.filter(weekly_rule=rule, source_date__gte=from_date, status="completed").update(
        weekly_rule=None, source_date=None
    )
    if from_date == rule.start_date:
        rule.delete()
        return
    rule.end_date = from_date - timedelta(days=1)
    rule.save(update_fields=["end_date"])
