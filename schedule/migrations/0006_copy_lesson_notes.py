from django.db import migrations


def copy_lesson_notes(apps, schema_editor):
    Lesson = apps.get_model("schedule", "Lesson")
    LessonComment = apps.get_model("schedule", "LessonComment")
    for lesson in Lesson.objects.exclude(notes="").iterator():
        LessonComment.objects.create(lesson_id=lesson.pk, body=lesson.notes)


class Migration(migrations.Migration):
    dependencies = [("schedule", "0005_lessoncomment")]

    operations = [migrations.RunPython(copy_lesson_notes, migrations.RunPython.noop)]
