"""Weekly school lessons and a shared teacher's calendar constraints."""

from datetime import date, timedelta

from django.db.models import Q

from schedule.models import Lesson, WeeklyRule
from schedule.services import ensure_occurrences as ensure_tutor_occurrences, overlaps

from .models import SchoolLesson, SchoolWeeklyRule


def ensure_occurrences(start: date, end: date):
    rules = SchoolWeeklyRule.objects.filter(start_date__lte=end).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=start)
    ).select_related("school_class")
    created = []
    for rule in rules:
        cursor = max(start, rule.start_date)
        cursor += timedelta(days=(rule.weekday - cursor.weekday()) % 7)
        last = min(end, rule.end_date) if rule.end_date else end
        while cursor <= last:
            created.append(SchoolLesson(
                school_class=rule.school_class, date=cursor, time=rule.time,
                duration_min=rule.duration_min, topic=rule.topic,
                weekly_rule=rule, source_date=cursor,
            ))
            cursor += timedelta(days=7)
    SchoolLesson.objects.bulk_create(created, ignore_conflicts=True)


def check_collision(day, time_value, duration, exclude_id=None):
    ensure_occurrences(day, day)
    ensure_tutor_occurrences(day, day)
    for lesson in SchoolLesson.objects.filter(date=day).exclude(status="cancelled").select_related("school_class"):
        if lesson.id != exclude_id and overlaps(time_value, duration, lesson.time, lesson.duration_min):
            raise ValueError(f"В это время уже есть урок: {lesson.school_class.name}, {lesson.time:%H:%M}")
    for lesson in Lesson.objects.filter(date=day).exclude(status="cancelled").select_related("student"):
        if overlaps(time_value, duration, lesson.time, lesson.duration_min):
            raise ValueError(f"В это время уже есть занятие: {lesson.student.name}, {lesson.time:%H:%M}")


def check_rule_collision(weekday, time_value, duration, start, end=None, exclude_id=None):
    for rule in SchoolWeeklyRule.objects.filter(weekday=weekday, start_date__lte=end or date.max).select_related("school_class"):
        if rule.id == exclude_id or (rule.end_date and rule.end_date < start):
            continue
        if overlaps(time_value, duration, rule.time, rule.duration_min):
            raise ValueError(f"Урок пересекается с серией класса {rule.school_class.name} в {rule.time:%H:%M}")
    for rule in WeeklyRule.objects.filter(weekday=weekday, start_date__lte=end or date.max).select_related("student"):
        if rule.end_date and rule.end_date < start:
            continue
        if overlaps(time_value, duration, rule.time, rule.duration_min):
            raise ValueError(f"Урок пересекается с занятием {rule.student.name} в {rule.time:%H:%M}")


def check_one_off_future_collisions(weekday, time_value, duration, start, end=None, exclude_id=None):
    school = SchoolLesson.objects.filter(date__gte=start).exclude(status="cancelled").select_related("school_class")
    tutor = Lesson.objects.filter(date__gte=start).exclude(status="cancelled").select_related("student")
    if end:
        school = school.filter(date__lte=end)
        tutor = tutor.filter(date__lte=end)
    for lesson in school:
        if lesson.weekly_rule_id and not lesson.is_override:
            continue
        if lesson.date.weekday() == weekday and overlaps(time_value, duration, lesson.time, lesson.duration_min):
            raise ValueError(f"Серия пересекается с уроком {lesson.school_class.name} {lesson.date:%d.%m} в {lesson.time:%H:%M}")
    for lesson in tutor:
        if lesson.weekly_rule_id and not lesson.is_override:
            continue
        if lesson.date.weekday() == weekday and overlaps(time_value, duration, lesson.time, lesson.duration_min):
            raise ValueError(f"Серия пересекается с занятием {lesson.student.name} {lesson.date:%d.%m} в {lesson.time:%H:%M}")


def change_series(rule, from_date, *, school_class, weekday, time_value, duration, topic):
    if from_date < rule.start_date or (rule.end_date and from_date > rule.end_date):
        raise ValueError("Дата изменения не входит в серию")
    new_start = from_date + timedelta(days=(weekday - from_date.weekday()) % 7)
    if rule.end_date and new_start > rule.end_date:
        raise ValueError("Новый день недели выходит за пределы серии")
    check_rule_collision(weekday, time_value, duration, new_start, rule.end_date, rule.id)
    check_one_off_future_collisions(weekday, time_value, duration, new_start, rule.end_date, rule.id)
    SchoolLesson.objects.filter(weekly_rule=rule, source_date__gte=from_date, is_override=False).delete()
    SchoolLesson.objects.filter(weekly_rule=rule, source_date__gte=from_date, is_override=True).update(
        weekly_rule=None, source_date=None
    )
    if from_date == rule.start_date:
        rule.school_class = school_class
        rule.weekday = weekday
        rule.time = time_value
        rule.duration_min = duration
        rule.topic = topic
        rule.start_date = new_start
        rule.save()
        return rule
    old_end = rule.end_date
    rule.end_date = from_date - timedelta(days=1)
    rule.save(update_fields=["end_date"])
    return SchoolWeeklyRule.objects.create(
        school_class=school_class, weekday=weekday, time=time_value,
        duration_min=duration, topic=topic, start_date=new_start, end_date=old_end,
    )


def end_series(rule, from_date):
    if from_date < rule.start_date or (rule.end_date and from_date > rule.end_date):
        raise ValueError("Дата завершения не входит в серию")
    SchoolLesson.objects.filter(weekly_rule=rule, source_date__gte=from_date).exclude(status="completed").delete()
    SchoolLesson.objects.filter(weekly_rule=rule, source_date__gte=from_date, status="completed").update(
        weekly_rule=None, source_date=None
    )
    if from_date == rule.start_date:
        rule.delete()
    else:
        rule.end_date = from_date - timedelta(days=1)
        rule.save(update_fields=["end_date"])
