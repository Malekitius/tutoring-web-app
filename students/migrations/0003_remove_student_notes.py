from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("students", "0002_student_opening_balance_rub"),
        ("schedule", "0010_move_student_notes"),
    ]

    operations = [migrations.RemoveField(model_name="student", name="notes")]
