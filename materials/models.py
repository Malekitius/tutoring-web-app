import uuid

from django.db import models

from school.models import SchoolClass
from students.models import Student


def material_path(instance, filename):
    return f"materials/{instance.id}.pdf"


class Material(models.Model):
    KIND_CHOICES = [("textbook", "Учебник"), ("workbook", "Задачник"), ("other", "Другой материал")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="materials", null=True, blank=True)
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="materials", null=True, blank=True)
    title = models.CharField(max_length=160)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="other")
    file = models.FileField(upload_to=material_path)
    original_name = models.CharField(max_length=255)
    page_count = models.PositiveIntegerField(default=0)
    text_page_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "id"]
        constraints = [models.CheckConstraint(
            condition=(models.Q(student__isnull=False, school_class__isnull=True) |
                       models.Q(student__isnull=True, school_class__isnull=False)),
            name="material_exactly_one_owner",
        )]


class MaterialPage(models.Model):
    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="pages")
    number = models.PositiveIntegerField()
    text = models.TextField(blank=True)

    class Meta:
        ordering = ["number"]
        constraints = [models.UniqueConstraint(fields=["material", "number"], name="unique_material_page")]
