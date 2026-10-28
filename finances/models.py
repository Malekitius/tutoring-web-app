import uuid

from django.db import models

from students.models import Student


class Payment(models.Model):
    """Money received for a student's account; it may cover several lessons."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="payments")
    paid_on = models.DateField()
    amount_rub = models.PositiveIntegerField()
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_on", "-created_at"]

    def __str__(self):
        return f"{self.student.name}: {self.amount_rub} ₽ ({self.paid_on})"
