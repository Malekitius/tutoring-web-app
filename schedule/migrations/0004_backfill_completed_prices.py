from django.db import migrations


def backfill_prices(apps, schema_editor):
    Lesson = apps.get_model("schedule", "Lesson")
    lessons = Lesson.objects.filter(status="completed", charged_price_rub__isnull=True).select_related("student")
    for lesson in lessons.iterator():
        lesson.charged_price_rub = lesson.student.price_rub
        lesson.save(update_fields=["charged_price_rub"])


class Migration(migrations.Migration):
    dependencies = [
        ("schedule", "0003_lesson_charged_price_rub"),
        ("students", "0002_student_opening_balance_rub"),
    ]
    operations = [migrations.RunPython(backfill_prices, migrations.RunPython.noop)]
