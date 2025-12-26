from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("metrics", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="metricsevent",
            name="source",
            field=models.CharField(
                choices=[
                    ("profile", "profile"),
                    ("ask_ai", "ask_ai"),
                    ("diet", "diet"),
                    ("workout_plan", "workout_plan"),
                ],
                default="profile",
                max_length=40,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="metricsevent",
            name="source_id",
            field=models.CharField(default="", max_length=128),
            preserve_default=False,
        ),
        migrations.AddIndex(
            model_name="metricsevent",
            index=models.Index(fields=["source", "source_id"], name="metrics_event_source_idx"),
        ),
        migrations.AddConstraint(
            model_name="metricsevent",
            constraint=models.UniqueConstraint(
                fields=("event_type", "source", "source_id"),
                condition=~Q(source_id=""),
                name="metrics_event_unique_source",
            ),
        ),
    ]
