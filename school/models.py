import uuid

from django.db import models


class SchoolClass(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField("Название класса", max_length=80)
    subject = models.CharField("Предмет", max_length=80)
    level = models.CharField("Уровень", max_length=80, default="Базовый")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "subject"]
        constraints = [models.UniqueConstraint(fields=["name", "subject"], name="unique_school_class_subject")]
        verbose_name = "Класс"
        verbose_name_plural = "Классы"

    def __str__(self):
        return f"{self.name} · {self.subject}"


class SchoolStudent(models.Model):
    GROUP_CHOICES = [
        ("support", "Нужна поддержка"),
        ("mastering", "Осваивает программу"),
        ("advanced", "Готов к углублению"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="students")
    name = models.CharField("Имя ученика", max_length=120)
    group = models.CharField("Группа", max_length=10, choices=GROUP_CHOICES, default="mastering")
    birth_date = models.DateField("Дата рождения", null=True, blank=True)
    comment = models.TextField("Комментарий", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "Ученик школы"
        verbose_name_plural = "Ученики школы"

    def __str__(self):
        return self.name


class SchoolWeeklyRule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="weekly_rules")
    weekday = models.PositiveSmallIntegerField()
    time = models.TimeField()
    duration_min = models.PositiveSmallIntegerField(default=45)
    topic = models.CharField(max_length=160, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["weekday", "time"]


class SchoolLesson(models.Model):
    STATUS_CHOICES = [
        ("planned", "Запланировано"),
        ("completed", "Проведено"),
        ("cancelled", "Отменено"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="lessons")
    date = models.DateField()
    time = models.TimeField()
    duration_min = models.PositiveSmallIntegerField(default=45)
    topic = models.CharField(max_length=160, blank=True)
    comment = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="planned")
    weekly_rule = models.ForeignKey(SchoolWeeklyRule, on_delete=models.SET_NULL, null=True, blank=True, related_name="lessons")
    source_date = models.DateField(null=True, blank=True)
    is_override = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "time", "school_class__name"]
        constraints = [models.UniqueConstraint(fields=["weekly_rule", "source_date"], name="unique_school_rule_occurrence")]

    def __str__(self):
        return f"{self.school_class} — {self.date} {self.time:%H:%M}"


class SchoolWorksheet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="worksheets")
    kind = models.CharField(max_length=10, choices=[("lesson", "На уроке"), ("homework", "Домашнее задание")])
    title = models.CharField(max_length=160)
    instructions = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class SchoolWorksheetItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    worksheet = models.ForeignKey(SchoolWorksheet, on_delete=models.CASCADE, related_name="items")
    source = models.ForeignKey("assignments.Exercise", on_delete=models.SET_NULL, null=True, blank=True)
    position = models.PositiveSmallIntegerField(default=0)
    title = models.CharField(max_length=160)
    prompt = models.TextField()
    answer = models.TextField(blank=True)
    source_ref = models.CharField(max_length=1200, blank=True)

    class Meta:
        ordering = ["position", "id"]
