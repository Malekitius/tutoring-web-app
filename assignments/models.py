import uuid

from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

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
    source_ref = models.CharField(max_length=1200, blank=True)

    class Meta:
        ordering = ["position", "id"]


def figure_path(instance, filename):
    return f"task-figures/{instance.id}.png"


class TaskFigure(models.Model):
    """An owned snapshot: worksheet figures survive edits to library exercises."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, null=True, blank=True, related_name="figures")
    worksheet_item = models.ForeignKey(WorksheetItem, on_delete=models.CASCADE, null=True, blank=True, related_name="figures")
    school_item = models.ForeignKey("school.SchoolWorksheetItem", on_delete=models.CASCADE, null=True, blank=True, related_name="figures")
    file = models.FileField(upload_to=figure_path)
    position = models.PositiveSmallIntegerField(default=0)
    source_title = models.CharField(max_length=160, blank=True)
    source_page = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [models.CheckConstraint(
            condition=(models.Q(exercise__isnull=False, worksheet_item__isnull=True, school_item__isnull=True) |
                       models.Q(exercise__isnull=True, worksheet_item__isnull=False, school_item__isnull=True) |
                       models.Q(exercise__isnull=True, worksheet_item__isnull=True, school_item__isnull=False)),
            name="task_figure_one_owner",
        )]


@receiver(post_delete, sender=TaskFigure)
def cleanup_task_figure_file(sender, instance, **kwargs):
    if not instance.file:
        return
    storage, name = instance.file.storage, instance.file.name
    def remove_unreferenced():
        if not TaskFigure.objects.filter(file=name).exists():
            storage.delete(name)
    transaction.on_commit(remove_unreferenced)




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
