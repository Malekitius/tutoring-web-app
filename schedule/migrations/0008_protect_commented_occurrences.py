from django.db import migrations


def protect_commented_occurrences(apps, schema_editor):
    Lesson = apps.get_model("schedule", "Lesson")
    Lesson.objects.filter(
        weekly_rule__isnull=False,
        comments__isnull=False,
        is_override=False,
    ).update(is_override=True)


class Migration(migrations.Migration):
    dependencies = [("schedule", "0007_remove_lesson_notes")]

    operations = [migrations.RunPython(protect_commented_occurrences, migrations.RunPython.noop)]
