import uuid

from django.db import models


class Student(models.Model):
    STATUS_CHOICES = [("active", "Занимается"), ("paused", "На паузе")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField("Имя ученика", max_length=120)
    grade = models.PositiveSmallIntegerField("Класс")
    status = models.CharField("Статус", max_length=10, choices=STATUS_CHOICES, default="active")
    goal = models.TextField("Общая цель", blank=True)
    price_rub = models.PositiveIntegerField("Стоимость занятия", default=0)
    opening_balance_rub = models.IntegerField("Начальный остаток, ₽", default=0)
    duration_min = models.PositiveSmallIntegerField("Длительность, мин", default=60)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "name"]
        verbose_name = "Ученик"
        verbose_name_plural = "Ученики"

    def __str__(self):
        return self.name


class Subject(models.Model):
    LEVEL_CHOICES = [(level, level.capitalize()) for level in ("начальный", "базовый", "уверенный", "продвинутый")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField("Предмет", max_length=80)
    icon = models.CharField("Иконка", max_length=32, blank=True, default="")
    level = models.CharField("Уровень", max_length=20, choices=LEVEL_CHOICES, default="базовый")
    goal = models.TextField("Цель по предмету", blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["student", "name"], name="unique_student_subject")]
        ordering = ["name"]
        verbose_name = "Предмет"
        verbose_name_plural = "Предметы"

    def __str__(self):
        return f"{self.student.name}: {self.name}"


class Topic(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="topics")
    title = models.CharField("Тема", max_length=160)
    mastery = models.PositiveSmallIntegerField("Освоение", default=0)
    notes = models.TextField("Комментарий", blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "title"]
        verbose_name = "Тема"
        verbose_name_plural = "Темы"

    def __str__(self):
        return self.title
