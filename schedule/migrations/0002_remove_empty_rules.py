from django.db import migrations
from django.db.models import F


def remove_empty_rules(apps, schema_editor):
    WeeklyRule = apps.get_model("schedule", "WeeklyRule")
    Lesson = apps.get_model("schedule", "Lesson")
    empty_rules = WeeklyRule.objects.filter(end_date__lt=F("start_date"))
    Lesson.objects.filter(weekly_rule__in=empty_rules).update(
        weekly_rule=None, source_date=None, is_override=False
    )
    empty_rules.delete()


class Migration(migrations.Migration):
    dependencies = [("schedule", "0001_initial")]
    operations = [migrations.RunPython(remove_empty_rules, migrations.RunPython.noop)]
