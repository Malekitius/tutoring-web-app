import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("schedule", "0010_move_student_notes")]

    operations = [
        migrations.AlterField(
            model_name="lessoncomment",
            name="student",
            field=models.ForeignKey(
                to="students.student", related_name="notes_list",
                on_delete=django.db.models.deletion.CASCADE,
            ),
        ),
    ]
