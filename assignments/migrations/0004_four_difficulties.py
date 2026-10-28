from django.db import migrations, models


def convert_difficulties(apps, schema_editor):
    Exercise = apps.get_model("assignments", "Exercise")
    # Old 3 was medium and old 5 was advanced. Olympiad is a new explicit level.
    for old, new in ((5, 3), (4, 3), (3, 2)):
        Exercise.objects.filter(difficulty=old).update(difficulty=new)


class Migration(migrations.Migration):
    dependencies = [("assignments", "0003_expand_subject")]
    operations = [
        migrations.RunPython(convert_difficulties, migrations.RunPython.noop),
        migrations.AlterField(model_name="exercise", name="difficulty", field=models.PositiveSmallIntegerField(default=2)),
    ]
