import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("schedule", "0008_protect_commented_occurrences"),
        ("students", "0002_student_opening_balance_rub"),
    ]

    operations = [
        migrations.AddField(
            model_name="lessoncomment",
            name="student",
            field=models.ForeignKey(
                to="students.student", related_name="notes_list",
                on_delete=django.db.models.deletion.CASCADE,
                null=True, blank=True,
            ),
        ),
        migrations.AlterField(
            model_name="lessoncomment",
            name="lesson",
            field=models.ForeignKey(
                to="schedule.lesson", related_name="comments",
                on_delete=django.db.models.deletion.SET_NULL,
                null=True, blank=True,
            ),
        ),
        migrations.AlterField(
            model_name="lessoncomment",
            name="body",
            field=models.TextField(max_length=5000),
        ),
    ]
