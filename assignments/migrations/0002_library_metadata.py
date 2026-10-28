from django.db import migrations, models
import django.db.models.deletion


def copy_grades(apps, schema_editor):
    Exercise = apps.get_model("assignments", "Exercise")
    ExerciseGrade = apps.get_model("assignments", "ExerciseGrade")
    ExerciseGrade.objects.bulk_create(
        ExerciseGrade(exercise_id=item.id, grade=item.grade)
        for item in Exercise.objects.all().only("id", "grade")
    )


class Migration(migrations.Migration):
    dependencies = [("assignments", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="exercise", name="subtopic",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="exercise", name="difficulty",
            field=models.PositiveSmallIntegerField(default=3),
        ),
        migrations.CreateModel(
            name="ExerciseGrade",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("grade", models.PositiveSmallIntegerField(db_index=True)),
                ("exercise", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="grade_levels", to="assignments.exercise")),
            ],
            options={"ordering": ["grade"]},
        ),
        migrations.AddConstraint(
            model_name="exercisegrade",
            constraint=models.UniqueConstraint(fields=("exercise", "grade"), name="unique_exercise_grade"),
        ),
        migrations.RunPython(copy_grades, migrations.RunPython.noop),
        migrations.RemoveField(model_name="exercise", name="grade"),
    ]
