from django.conf import settings
from django.db import models


class CabinetPreferences(models.Model):
    class Mode(models.TextChoices):
        TUTORING = "tutoring", "Репетиторство"
        SCHOOL = "school", "Школа"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    start_mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.TUTORING)
