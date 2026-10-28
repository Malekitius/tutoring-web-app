import uuid

from django.db import models

from students.models import Student, Subject


class WeeklyRule(models.Model):
    """A weekly pattern; individual lessons can diverge without changing it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="weekly_rules")
    subject = models.ForeignKey(Subject, on_delete=models.SET_NULL, null=True, blank=True)
    weekday = models.PositiveSmallIntegerField()  # Monday = 0
    time = models.TimeField()
    duration_min = models.PositiveSmallIntegerField(default=60)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["weekday", "time"]


class Lesson(models.Model):
    STATUS_CHOICES = [
        ("planned", "Запланировано"),
        ("completed", "Проведено"),
        ("cancelled", "Отменено"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="lessons")
    subject = models.ForeignKey(Subject, on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField()
    time = models.TimeField()
    duration_min = models.PositiveSmallIntegerField(default=60)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="planned")
    charged_price_rub = models.PositiveIntegerField(null=True, blank=True)
    weekly_rule = models.ForeignKey(WeeklyRule, on_delete=models.SET_NULL, null=True, blank=True, related_name="lessons")
    source_date = models.DateField(null=True, blank=True)
    is_override = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "time", "student__name"]
        constraints = [
            models.UniqueConstraint(fields=["weekly_rule", "source_date"], name="unique_rule_occurrence"),
        ]

    def __str__(self):
        return f"{self.student.name} — {self.date} {self.time:%H:%M}"


class LessonComment(models.Model):
    PRIORITY_CHOICES = [
        ("none", "Без приоритета"),
        ("low", "Низкий"),
        ("medium", "Средний"),
        ("high", "Высокий"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="notes_list")
    lesson = models.ForeignKey(Lesson, on_delete=models.SET_NULL, null=True, blank=True, related_name="comments")
    body = models.TextField(max_length=5000)
    priority = models.CharField(max_length=6, choices=PRIORITY_CHOICES, default="none")
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
