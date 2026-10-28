from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("assignments", "0002_library_metadata")]

    operations = [
        migrations.AlterField(
            model_name="exercise", name="subject",
            field=models.CharField(max_length=80),
        ),
    ]
