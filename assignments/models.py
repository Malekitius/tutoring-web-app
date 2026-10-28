import uuid

from django.db import models

from schedule.models import Lesson
from students.models import Student


class Exercise(models.Model):
    """Reusable task; placed copies remain unchanged when this template is edited."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=160)
    prompt = models.TextField(max_length=10000)
    answer = models.TextField(max_length=10000, blank=True)
    subject = models.CharField(max_length=80)
    topic = models.CharField(max_length=160, blank=True)
    subtopic = models.CharField(max_length=160, blank=True)
    difficulty = models.PositiveSmallIntegerField(default=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "title"]


class ExerciseGrade(models.Model):
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name="grade_levels")
    grade = models.PositiveSmallIntegerField(db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["exercise", "grade"], name="unique_exercise_grade")]
        ordering = ["grade"]


class Worksheet(models.Model):
    KIND_CHOICES = [("lesson", "На уроке"), ("homework", "Домашнее задание")]
    STATUS_CHOICES = [("draft", "Черновик"), ("assigned", "Задано"),
                      ("submitted", "На проверке"), ("reviewed", "Проверено"),
                      ("revision", "На доработке")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="worksheets")
    lesson = models.ForeignKey(Lesson, on_delete=models.SET_NULL, null=True, blank=True, related_name="worksheets")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    title = models.CharField(max_length=160)
    instructions = models.TextField(max_length=5000, blank=True)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="draft")
    feedback = models.TextField(max_length=5000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class WorksheetItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    worksheet = models.ForeignKey(Worksheet, on_delete=models.CASCADE, related_name="items")
    source = models.ForeignKey(Exercise, on_delete=models.SET_NULL, null=True, blank=True)
    position = models.PositiveSmallIntegerField(default=0)
    title = models.CharField(max_length=160)
    prompt = models.TextField(max_length=10000)
    answer = models.TextField(max_length=10000, blank=True)

    class Meta:
        ordering = ["position", "id"]


def submission_path(instance, filename):
    extension = filename.rsplit(".", 1)[-1].lower()
    return f"assignments/{instance.worksheet_id}/{uuid.uuid4().hex}.{extension}"


class Submission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    worksheet = models.ForeignKey(Worksheet, on_delete=models.CASCADE, related_name="submissions")
    file = models.FileField(upload_to=submission_path)
    original_name = models.CharField(max_length=255)
    note = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
