from django.db import migrations


def move_student_notes(apps, schema_editor):
    database = schema_editor.connection.alias
    Student = apps.get_model("students", "Student")
    LessonComment = apps.get_model("schedule", "LessonComment")

    for comment in LessonComment.objects.using(database).filter(lesson__isnull=False).select_related("lesson").iterator():
        comment.student_id = comment.lesson.student_id
        comment.save(update_fields=["student"])

    for student in Student.objects.using(database).exclude(notes="").iterator():
        note = LessonComment.objects.using(database).create(
            student_id=student.pk,
            body=student.notes,
            priority="none",
        )
        LessonComment.objects.using(database).filter(pk=note.pk).update(
            created_at=student.updated_at,
            updated_at=student.updated_at,
        )


class Migration(migrations.Migration):
    dependencies = [("schedule", "0009_unify_student_notes")]

    operations = [migrations.RunPython(move_student_notes, migrations.RunPython.noop)]
